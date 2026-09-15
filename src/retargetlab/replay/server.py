"""Loopback-only native MuJoCo renderer for a verified saved-q bundle."""

from __future__ import annotations

import argparse
import base64
import gzip
import io
import json
import math
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import numpy as np

from retargetlab.robot.mujoco_model import MujocoKinematics

from .bundle import build, digest, read
from .webgl import motion_payload, scene_payload


class Replay:
    def __init__(self, bundle):
        self.bundle = Path(bundle)
        self.catalog = read(self.bundle / "catalog.json")
        self.runs = {r["id"]: r for r in self.catalog["runs"]}
        self.episodes = {}
        self.engines = {}
        self.renderers = {}
        self.scenes = {}
        self.motions = {}
        for filename, sha in self.catalog["files"].items():
            if digest(self.bundle / filename) != sha:
                raise ValueError(f"replay fingerprint changed: {filename}")
        for run in self.runs.values():
            model = run["model"]
            if digest(Path(model) / "manifest.json") != run["model_sha256"]:
                raise ValueError("replay model fingerprint changed")
            if model not in self.engines:
                self.engines[model] = MujocoKinematics(Path(model))

    def episode(self, run_id, episode_id):
        run = self.runs[run_id]
        entry = next((e for e in run["episodes"] if e["id"] == episode_id), None)
        if entry is None:
            raise ValueError("episode is not in this replay")
        key = (run_id, episode_id)
        if key not in self.episodes:
            self.episodes[key] = read(self.bundle / entry["file"])
        return self.episodes[key]

    def scene(self, run_id):
        run = self.runs[run_id]
        key = run["model"]
        if key not in self.scenes:
            self.scenes[key] = scene_payload(self.engines[key])
        return {"run": run_id, "model_sha256": run["model_sha256"], **self.scenes[key]}

    def motion(self, run_id, episode_id, stream):
        key = (run_id, episode_id, stream)
        if key not in self.motions:
            run = self.runs[run_id]
            sequence = self.episode(run_id, episode_id)["streams"][stream]
            payload = motion_payload(self.engines[run["model"]], run["joint_names"], sequence)
            # Bound the disposable display cache, not the frozen evidence bundle.
            if len(self.motions) >= 4:
                self.motions.pop(next(iter(self.motions)))
            self.motions[key] = {
                "run": run_id,
                "episode": episode_id,
                "stream": stream,
                "model_sha256": run["model_sha256"],
                **payload,
            }
        return self.motions[key]

    def frame(
        self,
        run_id,
        episode_id,
        stream,
        index,
        azimuth=45,
        elevation=-15,
        zoom=1,
        overlays=True,
        traces=False,
    ):
        import mujoco
        from PIL import Image

        if (
            not all(math.isfinite(v) for v in (azimuth, elevation, zoom))
            or not 0.25 <= zoom <= 4
            or not -85 <= elevation <= 85
        ):
            raise ValueError("invalid camera")
        run = self.runs[run_id]
        seq = self.episode(run_id, episode_id)["streams"][stream]
        if index < 0 or index >= len(seq["frames"]):
            raise ValueError("frame index out of range")
        row = seq["frames"][index]
        engine = self.engines[run["model"]]
        engine.set_configuration(run["joint_names"], row["q"])
        model, data = engine.model, engine.data
        if run["model"] not in self.renderers:
            model.vis.global_.offwidth = 900
            model.vis.global_.offheight = 650
            model.vis.headlight.ambient[:] = [0.4, 0.4, 0.4]
            model.vis.headlight.diffuse[:] = [0.8, 0.8, 0.8]
            self.renderers[run["model"]] = mujoco.Renderer(model, height=650, width=900)
        renderer = self.renderers[run["model"]]
        lower, upper = np.array(seq["lower"]), np.array(seq["upper"])
        camera = mujoco.MjvCamera()
        camera.lookat[:] = (lower + upper) / 2
        camera.azimuth, camera.elevation = azimuth % 360, elevation
        # Bounding sphere fits every orientation and every saved frame in the episode.
        radius = float(np.linalg.norm(upper - lower)) / 2
        camera.distance = radius / math.sin(math.radians(model.vis.global_.fovy) / 2) * 1.08 / zoom
        option = mujoco.MjvOption()
        option.geomgroup[0] = 0
        option.sitegroup[:] = 0
        renderer.update_scene(data, camera=camera, scene_option=option)
        scene = renderer.scene

        def line(a, b, rgba, width):
            geom = scene.geoms[scene.ngeom]
            mujoco.mjv_initGeom(
                geom,
                mujoco.mjtGeom.mjGEOM_CAPSULE,
                np.zeros(3),
                np.zeros(3),
                np.eye(3).ravel(),
                np.array(rgba, dtype=np.float32),
            )
            mujoco.mjv_connector(
                geom, mujoco.mjtGeom.mjGEOM_CAPSULE, width, np.asarray(a), np.asarray(b)
            )
            scene.ngeom += 1

        if overlays:
            root = model.body(engine.metadata["root_frame"]).id
            root_rot, root_pos = data.xmat[root].reshape(3, 3), data.xpos[root]
            for target, actual in zip(row["targets"], row["actuals"], strict=True):
                tp, ap = root_pos + root_rot @ target[:3], root_pos + root_rot @ actual[:3]
                line(ap, tp, [1, 0.2, 0.9, 1], 0.003)
                for pose, length, width in ((actual, 0.06, 0.004), (target, 0.11, 0.0018)):
                    mat = np.empty(9)
                    mujoco.mju_quat2Mat(mat, np.array(pose[3:]))
                    rotation = root_rot @ mat.reshape(3, 3)
                    position = root_pos + root_rot @ pose[:3]
                    for axis, color in enumerate(
                        ([1, 0.18, 0.18, 1], [0.2, 1, 0.3, 1], [0.2, 0.55, 1, 1])
                    ):
                        line(position, position + rotation[:, axis] * length, color, width)
                # A white cross identifies the target even when the TCPs coincide.
                for axis in np.eye(3):
                    line(tp - axis * 0.012, tp + axis * 0.012, [1, 1, 1, 1], 0.002)
        if traces:
            root = model.body(engine.metadata["root_frame"]).id
            rotation = data.xmat[root].reshape(3, 3)
            origin = data.xpos[root]
            stride = max(1, math.ceil(len(seq["frames"]) / 180))
            samples = seq["frames"][::stride]
            if samples[-1] is not seq["frames"][-1]:
                samples = [*samples, seq["frames"][-1]]
            for arm, color in enumerate(([0.3, 0.9, 0.8, 1], [0.95, 0.65, 0.35, 1])):
                for i, (first, second) in enumerate(zip(samples[:-1], samples[1:])):
                    for field, rgba, width in (
                        ("actuals", color, 0.002),
                        ("targets", [0.8, 0.8, 0.8, 1], 0.001),
                    ):
                        if field == "targets" and i % 2:
                            continue
                        a = origin + rotation @ first[field][arm][:3]
                        b = origin + rotation @ second[field][arm][:3]
                        if np.linalg.norm(a - b) > 1e-9:
                            line(a, b, rgba, width)
        rgb = renderer.render()
        buffer = io.BytesIO()
        Image.fromarray(rgb).save(buffer, format="JPEG", quality=85)
        return {
            "run": run_id,
            "episode": episode_id,
            "stream": stream,
            "index": index,
            "frame": row,
            "image": "data:image/jpeg;base64," + base64.b64encode(buffer.getvalue()).decode(),
        }

    def close(self):
        for renderer in self.renderers.values():
            renderer.close()


def serve(bundle, port):
    replay = Replay(bundle)

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            try:
                url = urlparse(self.path)
                query = parse_qs(url.query)

                def one(key, default=None):
                    values = query.get(key, [default])
                    if len(values) != 1 or values[0] is None:
                        raise ValueError(f"missing or repeated parameter: {key}")
                    return values[0]

                if url.path == "/":
                    data = Path(__file__).with_name("viewer.html").read_bytes()
                    mime = "text/html; charset=utf-8"
                elif url.path in {
                    "/static/view3d.js",
                    "/static/playback.js",
                    "/static/vendor/three.module.min.js",
                    "/static/vendor/three.core.min.js",
                    "/static/vendor/OrbitControls.js",
                }:
                    data = (
                        Path(__file__)
                        .parent.joinpath(url.path.removeprefix("/static/"))
                        .read_bytes()
                    )
                    mime = "text/javascript; charset=utf-8"
                else:
                    mime = "application/json"
                    if url.path == "/api/catalog":
                        result = replay.catalog
                    elif url.path == "/api/episode":
                        result = replay.episode(one("run"), int(one("episode")))
                    elif url.path == "/api/scene":
                        result = replay.scene(one("run"))
                    elif url.path == "/api/motion":
                        result = replay.motion(one("run"), int(one("episode")), one("stream"))
                    elif url.path == "/api/frame":
                        result = replay.frame(
                            one("run"),
                            int(one("episode")),
                            one("stream"),
                            int(one("index")),
                            float(one("azimuth", "45")),
                            float(one("elevation", "-15")),
                            float(one("zoom", "1")),
                            one("overlays", "1") == "1",
                            one("traces", "0") == "1",
                        )
                    else:
                        self.send_error(404)
                        return
                    data = json.dumps(result, allow_nan=False).encode()
                self.send_response(200)
            except (ValueError, KeyError, StopIteration) as exc:
                data = json.dumps({"error": str(exc)}).encode()
                mime = "application/json"
                self.send_response(400)
            except Exception as exc:
                data = json.dumps({"error": f"render failed: {type(exc).__name__}: {exc}"}).encode()
                mime = "application/json"
                self.send_response(500)
            if "gzip" in self.headers.get("Accept-Encoding", "") and len(data) > 1024:
                data = gzip.compress(data, compresslevel=3)
                self.send_header("Content-Encoding", "gzip")
            self.send_header("Vary", "Accept-Encoding")
            self.send_header("Content-Type", mime)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

    server = HTTPServer(("127.0.0.1", port), Handler)
    print(f"Saved-q replay listening on http://127.0.0.1:{port}", flush=True)
    try:
        server.serve_forever()
    finally:
        server.server_close()
        replay.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    builder = sub.add_parser("build")
    builder.add_argument("--config", type=Path, required=True)
    builder.add_argument("--output", type=Path, required=True)
    viewer = sub.add_parser("serve")
    viewer.add_argument("--bundle", type=Path, required=True)
    viewer.add_argument("--port", type=int, default=17888)
    args = parser.parse_args()
    if args.command == "build":
        print(json.dumps(build(args.config, args.output)))
    else:
        serve(args.bundle, args.port)


if __name__ == "__main__":
    main()
