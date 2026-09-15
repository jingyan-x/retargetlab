import * as THREE from 'three';
import {OrbitControls} from '/static/vendor/OrbitControls.js';

function unpack(text, Type) {
  const raw = atob(text), bytes = new Uint8Array(raw.length);
  for (let i=0;i<raw.length;i++) bytes[i]=raw.charCodeAt(i);
  return new Type(bytes.buffer);
}
function quaternion(object, q, offset=0) {
  object.quaternion.set(q[offset+1],q[offset+2],q[offset+3],q[offset]);
}
function dispose(group) {
  group.traverse(o=>{o.geometry?.dispose();if(o.material)o.material.dispose();});
  group.clear();
}

export class RobotView {
  constructor(canvas) {
    this.renderer=new THREE.WebGLRenderer({canvas,antialias:true});
    this.renderer.setPixelRatio(Math.min(devicePixelRatio,1.5));
    this.scene=new THREE.Scene();
    this.scene.background=new THREE.Color('#f3f4f5');
    this.camera=new THREE.PerspectiveCamera(42,1,.005,200);
    this.camera.up.set(0,0,1);
    this.controls=new OrbitControls(this.camera,canvas);
    this.controls.enableDamping=true;
    this.dirty=true;this.controls.addEventListener('change',()=>{this.dirty=true;});
    this.controls.dampingFactor=.14;
    this.controls.screenSpacePanning=true;
    this.controls.zoomToCursor=true;
    this.controls.rotateSpeed=.7;
    this.controls.zoomSpeed=1.1;
    this.controls.minDistance=.03;
    this.controls.maxDistance=30;
    this.controls.mouseButtons={LEFT:THREE.MOUSE.ROTATE,MIDDLE:THREE.MOUSE.DOLLY,RIGHT:THREE.MOUSE.PAN};
    this.scene.add(new THREE.HemisphereLight(0xffffff,0x727b86,2.3));
    const light=new THREE.DirectionalLight(0xffffff,2.4);light.position.set(2,-3,5);this.scene.add(light);
    const fill=new THREE.DirectionalLight(0xffffff,1);fill.position.set(-3,2,1);this.scene.add(fill);
    this.robot=new THREE.Group();this.markers=new THREE.Group();this.paths=new THREE.Group();
    this.scene.add(this.robot,this.markers,this.paths);
    this.floor=new THREE.Mesh(new THREE.PlaneGeometry(200,200),new THREE.MeshBasicMaterial({color:0xf0f1f2,side:THREE.FrontSide}));
    this.grid=new THREE.GridHelper(20,200,0x9299a1,0xcdd1d5);this.grid.rotation.x=Math.PI/2;
    this.scene.add(this.floor,this.grid);
    this.resize=new ResizeObserver(()=>{const box=canvas.getBoundingClientRect();this.camera.aspect=box.width/box.height;this.camera.updateProjectionMatrix();this.renderer.setSize(box.width,box.height,false);this.dirty=true;});
    this.resize.observe(canvas);
    canvas.addEventListener('contextmenu',e=>e.preventDefault());
    canvas.addEventListener('dblclick',e=>this.focusAt(e));
    canvas.addEventListener('webglcontextlost',e=>{e.preventDefault();canvas.dispatchEvent(new CustomEvent('viewerror',{detail:'图形上下文已丢失，请刷新页面重新加载。'}));});
  }
  setScene(payload) {
    dispose(this.robot);dispose(this.markers);dispose(this.paths);
    this.payload=payload;this.bodies=[];this.meshObjects=[];
    for(let i=0;i<payload.body_count;i++){const body=new THREE.Group();this.robot.add(body);this.bodies.push(body);}
    const meshes=new Map();
    for(const g of payload.geoms){
      let geometry;const s=g.size;
      if(g.kind===7){
        if(!meshes.has(g.mesh)){const m=payload.meshes[g.mesh],geo=new THREE.BufferGeometry();geo.setAttribute('position',new THREE.BufferAttribute(unpack(m.vertices,Float32Array),3));geo.setIndex(new THREE.BufferAttribute(unpack(m.faces,Uint32Array),1));geo.computeVertexNormals();meshes.set(g.mesh,geo);}
        geometry=meshes.get(g.mesh);
      } else if(g.kind===6) geometry=new THREE.BoxGeometry(s[0]*2,s[1]*2,s[2]*2);
      else if(g.kind===2||g.kind===4){geometry=new THREE.SphereGeometry(1,24,16);geometry.scale(s[0],g.kind===2?s[0]:s[1],g.kind===2?s[0]:s[2]);}
      else if(g.kind===5){geometry=new THREE.CylinderGeometry(s[0],s[0],s[1]*2,24);geometry.rotateX(Math.PI/2);}
      else if(g.kind===3){geometry=new THREE.CapsuleGeometry(s[0],s[1]*2,8,20);geometry.rotateX(Math.PI/2);}
      const rgba=g.rgba,material=new THREE.MeshStandardMaterial({color:new THREE.Color().setRGB(...rgba.slice(0,3)),roughness:.65,metalness:.15,opacity:rgba[3],transparent:rgba[3]<1,side:THREE.DoubleSide});
      const object=new THREE.Mesh(geometry,material);object.position.fromArray(g.position);quaternion(object,g.quaternion_wxyz);object.name=g.name;
      this.bodies[g.body].add(object);this.meshObjects.push(object);
    }
    this.axes=[];this.errors=[];
    const cylinder=new THREE.CylinderGeometry(1,1,1,8);
    const segment=(parent,a,b,color,radius)=>{
      const delta=new THREE.Vector3().subVectors(b,a),mesh=new THREE.Mesh(cylinder.clone(),new THREE.MeshBasicMaterial({color}));
      mesh.position.copy(a).add(b).multiplyScalar(.5);mesh.quaternion.setFromUnitVectors(new THREE.Vector3(0,1,0),delta.clone().normalize());mesh.scale.set(radius,delta.length(),radius);parent.add(mesh);
    };
    for(let arm=0;arm<2;arm++){
      const items=[];
      for(const target of [true,false]){const axes=new THREE.Group();for(let a=0;a<3;a++){const end=new THREE.Vector3();end.setComponent(a,target?.11:.06);segment(axes,new THREE.Vector3(),end,[0xe33737,0x119447,0x206fe0][a],target?.0014:.003);}
        if(target)for(let a=0;a<3;a++){const p=new THREE.Vector3();p.setComponent(a,.012);segment(axes,p,p.clone().negate(),0x333b48,.0015);}
        this.markers.add(axes);items.push(axes);
      }
      this.axes.push(items);
      const geo=new THREE.BufferGeometry();geo.setAttribute('position',new THREE.BufferAttribute(new Float32Array(6),3));const line=new THREE.Line(geo,new THREE.LineBasicMaterial({color:0xcd20a0}));line.frustumCulled=false;this.markers.add(line);this.errors.push(line);
    }
  }
  setMotion(motion, sequence) {
    if(motion.frame_count!==sequence.frames.length||motion.body_count!==this.bodies.length)throw Error('模型与帧变换数量不一致');
    this.poses=unpack(motion.poses,Float64Array);
    if(this.poses.length!==motion.frame_count*motion.body_count*7)throw Error('帧变换数据长度错误');
    this.sequence=sequence;this.show(0);this.robot.updateMatrixWorld(true);
    const box=new THREE.Box3().setFromObject(this.robot);
    box.expandByPoint(new THREE.Vector3().fromArray(sequence.lower));box.expandByPoint(new THREE.Vector3().fromArray(sequence.upper));
    this.center=box.getCenter(new THREE.Vector3());this.radius=Math.max(.1,box.getSize(new THREE.Vector3()).length()/2);
    this.floor.position.z=box.min.z-.015;this.grid.position.z=this.floor.position.z+.001;
    this.reset();this.buildTraces();
  }
  show(index) {
    if(!this.poses)return;this.dirty=true;
    const base=index*this.bodies.length*7;
    for(let b=0;b<this.bodies.length;b++){const offset=base+b*7;this.bodies[b].position.fromArray(this.poses,offset);quaternion(this.bodies[b],this.poses,offset+3);}
    const root=this.bodies[this.payload.root_body],row=this.sequence.frames[index];
    for(let arm=0;arm<2;arm++){
      for(let kind=0;kind<2;kind++){const pose=row[kind?'actuals':'targets'][arm],axes=this.axes[arm][kind];axes.position.fromArray(pose).applyQuaternion(root.quaternion).add(root.position);quaternion(axes,pose,3);axes.quaternion.premultiply(root.quaternion);}
      const positions=this.errors[arm].geometry.attributes.position;this.axes[arm].forEach((o,i)=>positions.setXYZ(i,o.position.x,o.position.y,o.position.z));positions.needsUpdate=true;
    }
  }
  buildTraces() {
    dispose(this.paths);const rows=this.sequence.frames,stride=Math.max(1,Math.ceil(rows.length/400));
    const indices=[];for(let i=0;i<rows.length;i+=stride)indices.push(i);if(indices.at(-1)!==rows.length-1)indices.push(rows.length-1);
    for(let arm=0;arm<2;arm++)for(const target of [true,false]){
      const points=indices.map(i=>{const offset=(i*this.bodies.length+this.payload.root_body)*7;const q=new THREE.Quaternion(this.poses[offset+4],this.poses[offset+5],this.poses[offset+6],this.poses[offset+3]);return new THREE.Vector3().fromArray(rows[i][target?'targets':'actuals'][arm]).applyQuaternion(q).add(new THREE.Vector3().fromArray(this.poses,offset));});
      const material=target?new THREE.LineDashedMaterial({color:0x6e737a,dashSize:.018,gapSize:.012}):new THREE.LineBasicMaterial({color:arm?0xcd722b:0x108779});
      const line=new THREE.Line(new THREE.BufferGeometry().setFromPoints(points),material);line.computeLineDistances();this.paths.add(line);
    }
  }
  reset(direction='perspective') {
    if(!this.center)return;this.controls.target.copy(this.center);
    const distance=this.radius/Math.sin(THREE.MathUtils.degToRad(this.camera.fov/2))*1.1;
    const v=direction==='front'?new THREE.Vector3(1,0,.02):direction==='side'?new THREE.Vector3(0,-1,.02):direction==='top'?new THREE.Vector3(.001,0,1):new THREE.Vector3(1,-1,.65);
    this.camera.position.copy(this.center).addScaledVector(v.normalize(),distance);this.controls.update();this.controls.saveState();
  }
  zoom(factor){this.camera.position.sub(this.controls.target).multiplyScalar(factor).add(this.controls.target);this.controls.update();}
  focusAt(event){const rect=this.renderer.domElement.getBoundingClientRect(),pointer=new THREE.Vector2((event.clientX-rect.left)/rect.width*2-1,-(event.clientY-rect.top)/rect.height*2+1);const ray=new THREE.Raycaster();ray.setFromCamera(pointer,this.camera);const hit=ray.intersectObjects(this.meshObjects,false)[0];if(hit){const delta=hit.point.clone().sub(this.controls.target);this.controls.target.copy(hit.point);this.camera.position.add(delta);this.controls.update();}}
  render(){this.controls.update();if(this.dirty){this.renderer.render(this.scene,this.camera);this.dirty=false;}}
}
