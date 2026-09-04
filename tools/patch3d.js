;(function(){
/* OpenClaw: 3D 算力网络 自定义可视化 (chart 43) - 独立补丁版
   通过 tail_js_custom_extra.html 以 nonce 加载, 无缓存问题; 含 2D Canvas 回退 */
var __g3d={loaded:false,loading:false};


var __g3dHeatData={gpus:["GPU0", "GPU1", "GPU2", "GPU3", "GPU4", "GPU5", "GPU6", "GPU7"],values:[[11.4, 9.4, 13.2, 8.8, 13.1, 12.7, 11.5, 16.5, 14.3, 19.0, 17.6, 19.0, 22.6, 26.4, 21.0, 21.6, 24.2, 25.8, 21.6, 18.7, 21.8, 12.8, 17.9, 12.1], [6.0, 5.1, 6.5, 10.7, 6.2, 10.4, 12.1, 11.4, 14.4, 12.1, 13.5, 15.9, 20.6, 19.2, 18.5, 20.5, 18.8, 16.6, 19.4, 17.1, 12.0, 13.0, 11.2, 12.8], [32.6, 28.5, 33.8, 27.1, 30.1, 33.8, 30.2, 34.4, 32.3, 38.9, 41.1, 40.8, 44.2, 40.3, 43.6, 42.6, 41.8, 39.9, 41.7, 41.1, 35.8, 35.8, 29.5, 33.4], [54.0, 56.1, 54.6, 50.5, 51.9, 55.1, 51.2, 56.1, 55.3, 56.5, 57.5, 64.4, 60.2, 61.8, 63.1, 66.8, 59.8, 61.8, 61.4, 62.6, 60.6, 59.4, 53.2, 53.1], [17.7, 21.3, 21.7, 15.4, 16.2, 17.6, 18.9, 22.3, 24.7, 23.7, 23.0, 27.6, 28.2, 30.3, 33.6, 31.3, 29.3, 29.2, 28.4, 22.0, 27.2, 24.7, 24.0, 22.1], [39.9, 39.4, 36.8, 41.3, 37.3, 38.3, 40.7, 41.7, 44.7, 44.0, 45.0, 47.5, 48.0, 50.7, 48.2, 54.8, 52.1, 47.4, 47.0, 46.3, 44.9, 41.4, 45.8, 45.7], [25.5, 25.1, 21.7, 22.0, 24.5, 24.9, 30.6, 26.7, 27.2, 36.2, 34.2, 32.4, 36.5, 33.0, 37.2, 40.6, 39.1, 36.8, 32.1, 31.5, 28.3, 31.6, 28.3, 29.0], [59.4, 58.0, 62.5, 64.1, 63.6, 64.2, 65.5, 66.4, 63.8, 67.7, 67.8, 66.5, 67.4, 70.0, 70.1, 73.3, 74.8, 69.8, 72.5, 71.5, 69.6, 63.4, 60.8, 59.6]]};

function __g3dTopology(){
  function mulberry32(a){return function(){a|=0;a=a+0x6D2B79F5|0;var t=Math.imul(a^a>>>15,1|a);t=t+Math.imul(t^t>>>7,61|t)^t;return((t^t>>>14)>>>0)/4294967296}}
  var rnd=mulberry32(20260814);
  var GROUPS={core:{color:'#22d3ee',size:0.42},compute:{color:'#3b82f6',size:0.32},storage:{color:'#2dd4bf',size:0.30},gpu:{color:'#a78bfa',size:0.36}};
  var N=58,nodes=[],golden=Math.PI*(3-Math.sqrt(5));
  for(var i=0;i<N;i++){
    var y=1-(i/(N-1))*2,rad=Math.sqrt(1-y*y),th=golden*i;
    var x=Math.cos(th)*rad,z=Math.sin(th)*rad;
    var inner=(i%9===0);
    var p={x:x*8.2*(inner?0.45:1),y:y*4.8*(inner?0.5:1),z:z*8.2*(inner?0.45:1)};
    if(inner){p.x+=(rnd()-0.5)*1.2;p.y+=(rnd()-0.5)*0.8;p.z+=(rnd()-0.5)*1.2;}
    var grp=i<12?'core':(i<36?'compute':(i<48?'storage':'gpu'));
    var g=GROUPS[grp];
    nodes.push({pos:p,group:grp,color:g.color,size:g.size*(inner?1.25:1),inner:inner,index:i,
                name:grp.toUpperCase()+'-'+(i<12?('0'+i).slice(-2):('0'+(i-11)).slice(-2))});
  }
  function dist(a,b){var dx=a.pos.x-b.pos.x,dy=a.pos.y-b.pos.y,dz=a.pos.z-b.pos.z;return Math.sqrt(dx*dx+dy*dy+dz*dz)}
  var links=[],seen={};
  function addLink(a,b,backbone){var k=a.index+'-'+b.index;if(seen[k])return;seen[k]=1;links.push({a:a,b:b,backbone:backbone});}
  for(var i=0;i<nodes.length;i++){
    var n=nodes[i];
    var sorted=nodes.map(function(o){return {j:o.index,d:dist(n,o)}}).filter(function(o){return o.d>0.01}).sort(function(x,y){return x.d-y.d});
    var k=n.inner?5:3;
    for(var s=0;s<Math.min(k,sorted.length);s++)addLink(n,nodes[sorted[s].j],false);
    if(i%4===0&&sorted.length>12)addLink(n,nodes[sorted[12].j],true);
  }
  for(var i=0;i<12;i++)addLink(nodes[i],nodes[(i+1)%12],true);
  return {nodes:nodes,links:links};
}

/* ---------- 3D 算力节点网络 (chart 43): NPC 主控 + 12 子节点, 荧光青绿链路 ---------- */
function __g3d3D(root){
  var W=root.clientWidth||800,H=root.clientHeight||300;
  var scene=new THREE.Scene();
  var camera=new THREE.PerspectiveCamera(50,W/H,0.1,200);
  camera.position.set(16,13,16);
  var renderer=new THREE.WebGLRenderer({antialias:true,alpha:true});
  renderer.setPixelRatio(Math.min(window.devicePixelRatio||1,2));
  renderer.setSize(W,H);
  root.appendChild(renderer.domElement);
  var controls=new THREE.OrbitControls(camera,renderer.domElement);
  controls.enableDamping=true;controls.dampingFactor=0.08;
  controls.autoRotate=true;controls.autoRotateSpeed=0.7;
  controls.minDistance=8;controls.maxDistance=60;
  controls.target.set(0,2,0);
  scene.fog=new THREE.FogExp2(0x0a1428,0.010);
  scene.add(new THREE.AmbientLight(0x8899bb,0.55));
  var dlight=new THREE.DirectionalLight(0xffffff,0.85);dlight.position.set(10,22,8);scene.add(dlight);
  var dlight2=new THREE.DirectionalLight(0x00ff9d,0.35);dlight2.position.set(-8,10,-10);scene.add(dlight2);
  var pl=new THREE.PointLight(0x00ff9d,1.1,40);pl.position.set(0,3,0);scene.add(pl);
  /* 数字电路基底网格 (荧光绿) */
  var gs=30,step=2.2,gpts=[];
  for(var i=-gs;i<=gs;i+=step){gpts.push(-gs,0,i,gs,0,i);gpts.push(i,0,-gs,i,0,gs);}
  var gridGeo=new THREE.BufferGeometry();
  gridGeo.setAttribute('position',new THREE.Float32BufferAttribute(gpts,3));
  scene.add(new THREE.LineSegments(gridGeo,new THREE.LineBasicMaterial({color:0x00ff9d,transparent:true,opacity:0.16})));
  var base=new THREE.Mesh(new THREE.PlaneGeometry(80,80),new THREE.MeshBasicMaterial({color:0x062a20,transparent:true,opacity:0.4}));
  base.rotation.x=-Math.PI/2;base.position.y=-0.02;scene.add(base);
  /* 中心光环 (缓慢旋转) */
  var ringGeo=new THREE.RingGeometry(1.7,1.95,48);
  var ring=new THREE.Mesh(ringGeo,new THREE.MeshBasicMaterial({color:0x00ff9d,transparent:true,opacity:0.6,side:THREE.DoubleSide}));
  ring.rotation.x=-Math.PI/2;ring.position.y=0.02;scene.add(ring);
  var ring2=new THREE.Mesh(new THREE.RingGeometry(2.6,2.66,48),new THREE.MeshBasicMaterial({color:0x00ff9d,transparent:true,opacity:0.25,side:THREE.DoubleSide}));
  ring2.rotation.x=-Math.PI/2;ring2.position.y=0.02;scene.add(ring2);
  /* 中心主控服务器 NPC-01 */
  var chassis=new THREE.Mesh(new THREE.BoxGeometry(2.0,1.3,1.1),
    new THREE.MeshPhongMaterial({color:0x14303c,emissive:0x00c46e,emissiveIntensity:0.28,shininess:70,specular:0x99ffcc}));
  chassis.position.set(0,0.85,0);scene.add(chassis);
  var front=new THREE.Mesh(new THREE.BoxGeometry(2.04,0.10,0.06),
    new THREE.MeshBasicMaterial({color:0x00ff9d,transparent:true,opacity:0.9}));
  front.position.set(0,0.85,0.56);scene.add(front);
  var ant=new THREE.Mesh(new THREE.CylinderGeometry(0.05,0.05,0.7,8),
    new THREE.MeshPhongMaterial({color:0x1a3a4a,emissive:0x00ff9d,emissiveIntensity:0.5,shininess:40}));
  ant.position.set(0,1.9,0);scene.add(ant);
  var tipGlow=new THREE.Mesh(new THREE.SphereGeometry(0.16,16,16),
    new THREE.MeshBasicMaterial({color:0x7dffd4,transparent:true,opacity:0.95}));
  tipGlow.position.set(0,2.3,0);scene.add(tipGlow);
  /* 12 个子算力节点: 圆环分布 + 起伏 */
  var satellites=[],N=12;
  function makeSat(i){
    var ang=i/N*Math.PI*2;
    var px=Math.cos(ang)*7.2, pz=Math.sin(ang)*7.2, py=1.6+1.1*Math.cos(i*2.4+1);
    var body=new THREE.Mesh(new THREE.OctahedronGeometry(0.62,0),
      new THREE.MeshPhongMaterial({color:0x1b2f3f,emissive:0x00ff9d,emissiveIntensity:0.12,shininess:90,specular:0x66ffcc,metalness:0.0}));
    body.position.set(px,py,pz);scene.add(body);
    var led=new THREE.Mesh(new THREE.SphereGeometry(0.13,12,12),
      new THREE.MeshBasicMaterial({color:0x7dffd4,transparent:true,opacity:0.95}));
    led.position.set(px+0.5,py+0.45,pz);scene.add(led);
    var ped=new THREE.Mesh(new THREE.CylinderGeometry(0.05,0.12,0.5,6),
      new THREE.MeshPhongMaterial({color:0x0e2a33,emissive:0x00ff9d,emissiveIntensity:0.2}));
    ped.position.set(px,0.25,pz);scene.add(ped);
    return {mesh:body,pos:new THREE.Vector3(px,py,pz),name:'SAT-'+('0'+(i+1)).slice(-2)};
  }
  for(var i=0;i<N;i++)satellites.push(makeSat(i));
  var centerInfo={pos:new THREE.Vector3(0,1.0,0),name:'NPC-01'};
  /* 荧光青绿链路: 中心↔子节点 + 环网 */
  var lpts=[],ringPts=[];
  satellites.forEach(function(s){lpts.push(0,1.0,0,s.pos.x,s.pos.y,s.pos.z);});
  for(var i=0;i<N;i++){
    var a=satellites[i].pos,b=satellites[(i+1)%N].pos;
    ringPts.push(a.x,a.y,a.z,b.x,b.y,b.z);
  }
  var linkGeo=new THREE.BufferGeometry();
  linkGeo.setAttribute('position',new THREE.Float32BufferAttribute(lpts,3));
  scene.add(new THREE.LineSegments(linkGeo,new THREE.LineBasicMaterial({color:0x00ff9d,transparent:true,opacity:0.85})));
  var ringGeo2=new THREE.BufferGeometry();
  ringGeo2.setAttribute('position',new THREE.Float32BufferAttribute(ringPts,3));
  scene.add(new THREE.LineSegments(ringGeo2,new THREE.LineBasicMaterial({color:0x00ff9d,transparent:true,opacity:0.35})));
  /* 辉光粒子 */
  var haloPts=[new THREE.Vector3(0,1.0,0)];
  satellites.forEach(function(s){haloPts.push(s.pos);});
  scene.add(new THREE.Points(new THREE.BufferGeometry().setFromPoints(haloPts),
    new THREE.PointsMaterial({color:0x00ff9d,size:0.5,transparent:true,opacity:0.35,blending:THREE.AdditiveBlending,depthWrite:false})));
  /* 数据包 (绿色/白色) 沿链路流动 */
  var packets=[],PACKET_N=28;
  var pGeo=new THREE.SphereGeometry(1,10,10);
  var linkPairs=satellites.map(function(s){return [centerInfo,s]});
  for(var i=0;i<N;i++)linkPairs.push([satellites[i],satellites[(i+1)%N]]);
  for(var i=0;i<PACKET_N;i++){
    var l=linkPairs[Math.floor(Math.random()*linkPairs.length)];
    var pm=new THREE.MeshBasicMaterial({color:(i%4===0?0xffffff:0x7dffd4),transparent:true,opacity:0.95});
    var p=new THREE.Mesh(pGeo,pm);p.scale.setScalar(0.13);scene.add(p);
    packets.push({mesh:p,link:l,t:Math.random(),speed:0.0018+Math.random()*0.003});
  }
  /* 标签 */
  function makeLabel(text,color,sx){
    var c=document.createElement('canvas');c.width=256;c.height=64;
    var ctx=c.getContext('2d');
    ctx.font='bold 30px "Noto Sans CJK SC","PingFang SC",sans-serif';
    ctx.textAlign='center';ctx.textBaseline='middle';
    ctx.shadowColor=color;ctx.shadowBlur=12;
    ctx.fillStyle=color;ctx.fillText(text,128,32);
    var sp=new THREE.Sprite(new THREE.SpriteMaterial({map:new THREE.CanvasTexture(c),transparent:true,depthTest:false}));
    sp.scale.set(sx||2.6,0.65,1);return sp;
  }
  var lc=makeLabel('NPC-01 主控服务器','#7dffd4',3.4);
  lc.position.set(0,3.0,0);scene.add(lc);
  satellites.forEach(function(s){
    var sp=makeLabel(s.name,'#7dffd4',1.6);
    sp.position.set(s.pos.x,s.pos.y+1.15,s.pos.z);scene.add(sp);
  });
  /* 交互 */
  var raycaster=new THREE.Raycaster(),mouse=new THREE.Vector2(),hovered=null;
  var tip=document.createElement('div');
  tip.style.cssText='position:absolute;pointer-events:none;z-index:6;background:rgba(8,17,36,.92);border:1px solid rgba(0,255,157,.5);color:#7dffd4;border-radius:6px;padding:4px 10px;font-size:12px;display:none;top:0;left:0';
  root.appendChild(tip);
  var hitTargets=[chassis,tipGlow].concat(satellites.map(function(s){return s.mesh}));
  var hitMeta=[{name:'NPC-01 主控服务器 · 分布式 GPU 集群核心'},{name:'NPC-01 主控服务器 · 分布式 GPU 集群核心'}];
  satellites.forEach(function(s){hitMeta.push({name:s.name+' 子算力节点'});});
  renderer.domElement.addEventListener('mousemove',function(e){
    var r=root.getBoundingClientRect();
    mouse.x=((e.clientX-r.left)/r.width)*2-1;mouse.y=-((e.clientY-r.top)/r.height)*2+1;
    tip.style.left=(e.clientX-r.left+14)+'px';tip.style.top=(e.clientY-r.top+10)+'px';
  });
  function animate(){
    requestAnimationFrame(animate);
    controls.update();
    var t=Date.now()/1000;
    ring.rotation.z+=0.004;ring2.rotation.z-=0.003;
    tipGlow.scale.setScalar(1+0.15*Math.sin(t*3));
    chassis.material.emissiveIntensity=0.28+0.1*Math.sin(t*2.2);
    satellites.forEach(function(s,i){
      s.mesh.rotation.y+=0.01;
      var pulse=1+0.1*Math.sin(t*2+i*1.3);
      s.mesh.scale.setScalar(pulse);
    });
    packets.forEach(function(p){
      p.t+=p.speed;
      if(p.t>=1){p.t=0;p.link=linkPairs[Math.floor(Math.random()*linkPairs.length)];}
      var a=p.link[0].pos,b=p.link[1].pos;
      p.mesh.position.lerpVectors(a,b,p.t);
    });
    raycaster.setFromCamera(mouse,camera);
    var hits=raycaster.intersectObjects(hitTargets);
    if(hits.length){
      var idx=hitTargets.indexOf(hits[0].object);
      if(hovered!==hits[0].object){
        if(hovered&&hovered.__s){hovered.scale.setScalar(hovered.__s);}
        hovered=hits[0].object;
        if(hovered.__s===undefined){hovered.__s=hovered.scale.x;}
        hovered.scale.setScalar(hovered.__s*1.35);
        tip.style.display='block';
      }
      tip.textContent=hitMeta[idx]?hitMeta[idx].name:'';
    }else{
      if(hovered&&hovered.__s){hovered.scale.setScalar(hovered.__s);}
      hovered=null;tip.style.display='none';
    }
    renderer.render(scene,camera);
  }
  animate();
  if(window.ResizeObserver){
    new ResizeObserver(function(){
      var w=root.clientWidth||W,h=root.clientHeight||H;
      camera.aspect=w/h;camera.updateProjectionMatrix();
      renderer.setSize(w,h);
    }).observe(root);
  }
  var ttl=document.createElement('div');
  ttl.style.cssText='position:absolute;top:8px;left:0;right:0;text-align:center;pointer-events:none;z-index:5';
  ttl.innerHTML='<div style="font-size:16px;font-weight:700;letter-spacing:5px;color:#7dffd4;text-shadow:0 0 16px rgba(0,255,157,.6)">分布式 GPU 算力集群 · 组网拓扑</div>';
  root.appendChild(ttl);
  var leg=document.createElement('div');
  leg.style.cssText='position:absolute;left:10px;bottom:8px;pointer-events:none;z-index:5;background:rgba(8,17,36,.6);border:1px solid rgba(0,255,157,.3);border-radius:8px;padding:6px 10px;font-size:10px;color:#9db1c8;line-height:1.8';
  leg.innerHTML='<div><span style="display:inline-block;width:9px;height:9px;border-radius:2px;background:#14303c;border:1px solid #00ff9d;margin-right:6px;vertical-align:middle"></span>NPC-01 主控服务器</div>'+
    '<div><span style="display:inline-block;width:8px;height:8px;border-radius:50%;background:#00ff9d;margin-right:6px;vertical-align:middle;box-shadow:0 0 8px #00ff9d"></span>子算力节点 SAT-01~12</div>'+
    '<div><span style="display:inline-block;width:14px;height:2px;background:#00ff9d;margin-right:6px;vertical-align:middle"></span>荧光数据链路</div>';
  root.appendChild(leg);
  var hint=document.createElement('div');
  hint.style.cssText='position:absolute;right:10px;bottom:8px;font-size:9px;color:#4b6a8c;pointer-events:none;z-index:5';
  hint.textContent='拖拽旋转 · 滚轮缩放 · 悬停查看节点';
  root.appendChild(hint);
}
/* ---------- 3D 立体热力图 (chart 42) ---------- */
function __g3d3DBars(root){
  var data=__g3dHeatData;
  var W=root.clientWidth||800,H=root.clientHeight||300;
  var scene=new THREE.Scene();
  var camera=new THREE.PerspectiveCamera(42,W/H,0.1,200);
  camera.position.set(17,13,19);
  var renderer=new THREE.WebGLRenderer({antialias:true,alpha:true});
  renderer.setPixelRatio(Math.min(window.devicePixelRatio||1,2));
  renderer.setSize(W,H);
  root.appendChild(renderer.domElement);
  var controls=new THREE.OrbitControls(camera,renderer.domElement);
  controls.enableDamping=true;controls.dampingFactor=0.08;
  controls.autoRotate=true;controls.autoRotateSpeed=0.6;
  controls.minDistance=10;controls.maxDistance=70;
  controls.target.set(0,2,0);
  scene.fog=new THREE.FogExp2(0x0a1428,0.006);
  scene.add(new THREE.AmbientLight(0x93a7c9,1.0));
  var dlight=new THREE.DirectionalLight(0xffffff,1.15);dlight.position.set(12,28,10);scene.add(dlight);
  var dlight2=new THREE.DirectionalLight(0x22d3ee,0.35);dlight2.position.set(-10,8,-8);scene.add(dlight2);
  var X=24,Z=8,x0=-12,z0=-4;
  var gpts=[];
  for(var i=0;i<=X;i++){gpts.push(x0+i,0,z0,x0+i,0,z0+Z);}
  for(var i=0;i<=Z;i++){gpts.push(x0,0,z0+i,x0+X,0,z0+i);}
  var gridGeo=new THREE.BufferGeometry();
  gridGeo.setAttribute('position',new THREE.Float32BufferAttribute(gpts,3));
  scene.add(new THREE.LineSegments(gridGeo,new THREE.LineBasicMaterial({color:0x3b82f6,transparent:true,opacity:0.16})));
  var base=new THREE.Mesh(new THREE.PlaneGeometry(X,Z),new THREE.MeshBasicMaterial({color:0x0c2547,transparent:true,opacity:0.42}));
  base.rotation.x=-Math.PI/2;scene.add(base);
  var edgePts=[x0,0.01,z0,x0+X,0.01,z0,x0+X,0.01,z0+Z,x0,0.01,z0+Z,x0,0.01,z0];
  var edgeGeo=new THREE.BufferGeometry();
  edgeGeo.setAttribute('position',new THREE.Float32BufferAttribute(edgePts,3));
  scene.add(new THREE.Line(edgeGeo,new THREE.LineBasicMaterial({color:0x22d3ee,transparent:true,opacity:0.5})));
  function cellColor(v){
    var stops=[[0,[22,51,110]],[25,[29,111,208]],[50,[34,184,230]],[75,[79,227,245]],[100,[215,248,255]]];
    for(var i=0;i<stops.length-1;i++){
      var v0=stops[i][0],c0=stops[i][1],v1=stops[i+1][0],c1=stops[i+1][1];
      if(v<=v1){var t=v1>v0?(v-v0)/(v1-v0):0;
        return new THREE.Color((c0[0]+(c1[0]-c0[0])*t)/255,(c0[1]+(c1[1]-c0[1])*t)/255,(c0[2]+(c1[2]-c0[2])*t)/255);}
    }
    return new THREE.Color(215/255,248/255,255/255);
  }
  var bars=[],barGeo=new THREE.BoxGeometry(0.82,1,0.82);
  var capGeo=new THREE.BoxGeometry(0.80,0.06,0.80);
  var capMat=new THREE.MeshPhongMaterial({color:0xeafcff,emissive:0x7de8f7,emissiveIntensity:0.45,specular:0xffffff,shininess:80,transparent:true,opacity:0.96});
  for(var g=0;g<8;g++){
    for(var h=0;h<24;h++){
      var v=data.values[g][h];
      var bh=Math.max(0.12,v*0.09);
      var col=cellColor(v);
      var mat=new THREE.MeshPhongMaterial({color:col,emissive:col.clone().multiplyScalar(0.16),specular:0xffffff,shininess:60,transparent:true,opacity:0.95});
      var bar=new THREE.Mesh(barGeo,mat);
      bar.scale.y=bh;
      bar.position.set(x0+h+0.5,bh/2,z0+g+0.5);
      bar.userData.baseCol=col.clone();
      scene.add(bar);
      var cap=new THREE.Mesh(capGeo,capMat);
      cap.scale.y=Math.max(0.05,bh*0.05);
      cap.position.set(x0+h+0.5,bh+0.015,z0+g+0.5);
      scene.add(cap);
      bars.push({mesh:bar,cap:cap,g:g,h:h,v:v});
    }
  }
  function makeLabel(text,color,sx){
    var c=document.createElement('canvas');c.width=256;c.height=64;
    var ctx=c.getContext('2d');
    ctx.font='bold 30px "Noto Sans CJK SC","PingFang SC",sans-serif';
    ctx.textAlign='center';ctx.textBaseline='middle';
    ctx.shadowColor=color;ctx.shadowBlur=10;
    ctx.fillStyle=color;ctx.fillText(text,128,32);
    var sp=new THREE.Sprite(new THREE.SpriteMaterial({map:new THREE.CanvasTexture(c),transparent:true,depthTest:false}));
    sp.scale.set(sx||2.2,0.55,1);return sp;
  }
  for(var h=0;h<24;h+=2){
    var sp=makeLabel(('0'+h).slice(-2)+':00','#7dd3fc',1.3);
    sp.position.set(x0+h+0.5,-0.7,z0-0.9);scene.add(sp);
  }
  for(var g=0;g<8;g++){
    var sp=makeLabel(data.gpus[g],'#7dd3fc',1.2);
    sp.position.set(x0-1.5,0.3,z0+g+0.5);scene.add(sp);
  }
  var raycaster=new THREE.Raycaster(),mouse=new THREE.Vector2(),hovered=null;
  var tip=document.createElement('div');
  tip.style.cssText='position:absolute;pointer-events:none;z-index:6;background:rgba(8,17,36,.92);border:1px solid rgba(34,211,238,.5);color:#7dd3fc;border-radius:6px;padding:4px 10px;font-size:12px;display:none;top:0;left:0';
  root.appendChild(tip);
  renderer.domElement.addEventListener('mousemove',function(e){
    var r=root.getBoundingClientRect();
    mouse.x=((e.clientX-r.left)/r.width)*2-1;mouse.y=-((e.clientY-r.top)/r.height)*2+1;
    tip.style.left=(e.clientX-r.left+14)+'px';tip.style.top=(e.clientY-r.top+10)+'px';
  });
  function resetBar(b){
    b.mesh.material.color.copy(b.mesh.userData.baseCol);
    b.mesh.material.emissive.copy(b.mesh.userData.baseCol).multiplyScalar(0.16);
    b.mesh.material.opacity=0.95;
    b.cap.material.emissiveIntensity=0.45;
  }
  function animate(){
    requestAnimationFrame(animate);
    controls.update();
    raycaster.setFromCamera(mouse,camera);
    var hits=raycaster.intersectObjects(bars.map(function(b){return b.mesh}));
    var info=null;
    if(hits.length){
      for(var qi=0;qi<hits.length;qi++){var qb=bars.find(function(b){return b.mesh===hits[qi].object});if(qb){info=qb;break;}}
    }
    if(info){
      if(hovered!==info){
        if(hovered){resetBar(hovered);}
        hovered=info;
        hovered.mesh.material.color.lerp(new THREE.Color(1,1,1),0.45);
        hovered.mesh.material.emissive.set(0x66eeff).multiplyScalar(0.3);
        hovered.mesh.material.opacity=1;
        hovered.cap.material.emissiveIntensity=0.9;
        tip.style.display='block';
      }
      tip.textContent=data.gpus[info.g]+'  ·  '+('0'+info.h).slice(-2)+':00  ·  '+info.v+'%';
    }else{
      if(hovered){resetBar(hovered);}
      hovered=null;tip.style.display='none';
    }
    renderer.render(scene,camera);
  }
  animate();
  if(window.ResizeObserver){
    new ResizeObserver(function(){
      var w=root.clientWidth||W,h=root.clientHeight||H;
      camera.aspect=w/h;camera.updateProjectionMatrix();
      renderer.setSize(w,h);
    }).observe(root);
  }
  var ttl=document.createElement('div');
  ttl.style.cssText='position:absolute;top:8px;left:0;right:0;text-align:center;pointer-events:none;z-index:5';
  ttl.innerHTML='<div style="font-size:15px;font-weight:700;letter-spacing:4px;color:#8ee7fb;text-shadow:0 0 14px rgba(34,211,238,.7)">GPU 利用率 · 3D 立体视图</div>';
  root.appendChild(ttl);
  var leg=document.createElement('div');
  leg.style.cssText='position:absolute;left:10px;bottom:8px;pointer-events:none;z-index:5;background:rgba(8,17,36,.55);border:1px solid rgba(56,189,248,.25);border-radius:8px;padding:6px 10px;font-size:10px;color:#9db1c8;line-height:1.6';
  leg.innerHTML='<div style="display:flex;align-items:center">利用率 &nbsp;<span style="display:inline-block;width:90px;height:8px;border-radius:4px;background:linear-gradient(90deg,#16336e,#1d6fd0,#22b8e6,#4fe3f5,#d7f8ff)"></span>&nbsp; 低→高</div>';
  root.appendChild(leg);
  var hint=document.createElement('div');
  hint.style.cssText='position:absolute;right:10px;bottom:8px;font-size:9px;color:#4b6a8c;pointer-events:none;z-index:5';
  hint.textContent='拖拽旋转 · 滚轮缩放';
  root.appendChild(hint);
}

/* ---------- 主入口 ---------- */
function __g3dLoadScripts(cb){
  if(__g3d.loaded){cb();return;}
  if(__g3d.loading){var t=setInterval(function(){if(__g3d.loaded){clearInterval(t);cb();}},100);return;}
  __g3d.loading=true;
  function add(src,next){
    var s=document.createElement('script');
    s.src=src;
    s.onload=function(){next&&next();};
    s.onerror=function(){next&&next();};
    document.head.appendChild(s);
  }
  add('/static/assets/three.min.js',function(){
    add('/static/assets/OrbitControls.js',function(){
      __g3d.loaded=true;
      cb();
    });
  });
}
function __g3dInit(holder){
  var box=holder.querySelector('.chart-container')||holder;
  if(box.querySelector('div[data-g3d-wrap]')) return;
  // 不删除 React 节点, 只隐藏表格并叠加 3D 层, 避免 removeChild NotFoundError
  var tbl=box.querySelector('table');
  if(tbl) tbl.style.display='none';
  var wrap=document.createElement('div');
  wrap.setAttribute('data-g3d-wrap','1');
  wrap.style.cssText='position:absolute;left:0;top:0;width:100%;height:100%;overflow:hidden;background:#0a1428;z-index:2';
  box.style.position='relative';
  box.appendChild(wrap);
  __g3dLoadScripts(function(){
    try{
      if(holder.classList.contains('dashboard-chart-id-42')){
        try{__g3d3DBars(wrap);}
        catch(e){wrap.innerHTML='<div style="color:#f87171;padding:20px;font-size:13px">3D 渲染失败: '+e.message+'</div>';}
      }else{
        var topo=__g3dTopology();
        try{
          __g3d3D(wrap,topo);
        }catch(e){
          __g3d2D(wrap,topo);
        }
      }
    }catch(e2){
      wrap.innerHTML='<div style="color:#f87171;padding:20px;font-size:13px">3D 渲染失败: '+e2.message+'</div>';
    }
  });
}
function __g3dTry(){
  ['.dashboard-chart-id-43','.dashboard-chart-id-42'].forEach(function(sel){
    var h=document.querySelector(sel);
    if(!h)return;
    var box=h.querySelector('.chart-container')||h;
    if(box.querySelector('div[data-g3d-wrap]'))return;
    box.setAttribute('data-g3d','1');
    __g3dInit(h);
  });
}
setTimeout(function(){
  try{
    var obs=new MutationObserver(__g3dTry);
    obs.observe(document.documentElement,{childList:true,subtree:true});
  }catch(e){}
  __g3dTry();
  setInterval(__g3dTry,3000);
},2000);
})();
