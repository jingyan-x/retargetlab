"""Browser display geometry and saved-q FK; never solve or step physics."""

import base64

import numpy as np


def packed(values, dtype):
    return base64.b64encode(np.asarray(values, dtype=dtype).tobytes()).decode("ascii")


def scene_payload(engine):
    import mujoco

    model = engine.model
    geoms, meshes = [], {}
    for i in range(model.ngeom):
        # Match the native viewer: group zero is hidden collision geometry.
        if model.geom_group[i] == 0 or model.geom_rgba[i, 3] == 0:
            continue
        kind = int(model.geom_type[i])
        if kind not in (2, 3, 4, 5, 6, 7):
            raise ValueError(f"unsupported display geom type: {kind}")
        mesh_id = int(model.geom_dataid[i]) if kind == 7 else None
        if mesh_id is not None and str(mesh_id) not in meshes:
            va, vn = int(model.mesh_vertadr[mesh_id]), int(model.mesh_vertnum[mesh_id])
            fa, fn = int(model.mesh_faceadr[mesh_id]), int(model.mesh_facenum[mesh_id])
            meshes[str(mesh_id)] = {
                "vertices": packed(model.mesh_vert[va : va + vn], "<f4"),
                "faces": packed(model.mesh_face[fa : fa + fn], "<u4"),
            }
        geoms.append(
            {
                "id": i,
                "name": mujoco.mj_id2name(model, mujoco.mjtObj.mjOBJ_GEOM, i),
                "body": int(model.geom_bodyid[i]),
                "kind": kind,
                "mesh": mesh_id,
                "position": model.geom_pos[i].tolist(),
                "quaternion_wxyz": model.geom_quat[i].tolist(),
                "size": model.geom_size[i].tolist(),
                "rgba": model.geom_rgba[i].tolist(),
            }
        )
    return {
        "body_count": model.nbody,
        "root_body": model.body(engine.metadata["root_frame"]).id,
        "geoms": geoms,
        "meshes": meshes,
    }


def motion_payload(engine, joint_names, sequence):
    rows = sequence["frames"]
    poses = np.empty((len(rows), engine.model.nbody, 7), dtype="<f8")
    for i, row in enumerate(rows):
        engine.set_configuration(joint_names, row["q"])
        poses[i, :, :3] = engine.data.xpos
        poses[i, :, 3:] = engine.data.xquat
    return {
        "frame_count": len(rows),
        "body_count": engine.model.nbody,
        "layout": "frame,body,xyz+wxyz;float64-le",
        "poses": packed(poses, "<f8"),
    }
