const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

function load() {
  const calls=[];
  const ctx=new Proxy({imageSmoothingEnabled:true,measureText:text=>({width:String(text).length*6})}, {
    get(target,key){if(key in target)return target[key];return (...args)=>calls.push({key,args,color:target.fillStyle});},
  });
  const canvas={width:384,height:240,getContext:()=>ctx,
    getBoundingClientRect:()=>({left:28,top:48,width:960,height:600}),
    parentElement:{getBoundingClientRect:()=>({left:20,top:40,width:976,height:616})}};
  const sandbox={document:{readyState:'loading',addEventListener(){},querySelector:()=>canvas,
    createElement:()=>({getContext:()=>ctx})},window:{addEventListener(){}},performance:{now:()=>1000},console};
  const file=path.join(__dirname,'../site/dashboard/roommate.js');
  const source=fs.readFileSync(file,'utf8').replace(/\}\)\(\);\s*$/,`window.testApi={CANVAS_W,CANVAS_H,ROOMS,ROOM_DOORS,ROOM_SPOTS,SPRITES,state,
    pickRoomSpot,computePath,pickPose,drawResident,getCtx,paintApartmentOnce,retargetSprites,
    hitTestFurniture,_refreshGeometry,bubbleAnchor,
    roomWalkPath,SOLID_FURNITURE,paintApartment,SPRITE_DRAW,positionBubble,appearance:typeof residentAppearance==='function'?residentAppearance:null};})();`);
  vm.runInNewContext(source,sandbox);
  return {api:sandbox.window.testApi,canvas,ctx,calls};
}

test('full apartment backing buffer matches every room and the declared canvas',()=>{
  const {api,canvas}=load(); api.getCtx();
  assert.equal(canvas.width,api.CANVAS_W);assert.equal(canvas.height,api.CANVAS_H);
  for(const r of api.ROOMS) assert.ok(r.x+r.w<=canvas.width && r.y+r.h<=canvas.height,r.id);
  const html=fs.readFileSync(path.join(__dirname,'../site/dashboard/roommate.html'),'utf8');
  assert.ok(html.includes(`width="${api.CANVAS_W}" height="${api.CANVAS_H}"`));
});

test('room doors lie on room edges and cross-room paths use the central corridor',()=>{
  const {api}=load(), corridor=api.ROOMS.find(r=>r.id==='hallway');
  for(const [id,door] of Object.entries(api.ROOM_DOORS)){
    const r=api.ROOMS.find(r=>r.id===id);
    assert.ok(door.x>=r.x && door.x<=r.x+r.w && door.y>=r.y && door.y<=r.y+r.h,id);
    assert.ok([r.x,r.x+r.w].includes(door.x)||[r.y,r.y+r.h].includes(door.y),id+' door is on boundary');
  }
  const route=api.computePath('kitchen',api.pickRoomSpot('kitchen',1,'做早餐'),
    'second',api.pickRoomSpot('second',2,'午睡'));
  assert.ok(route.some(p=>p.y>=corridor.y && p.y<=corridor.y+corridor.h));
  assert.ok(route.every(p=>p.x>=0 && p.x<=api.CANVAS_W && p.y>=0 && p.y<=api.CANVAS_H));
});

test('activity spots follow the matching furniture within the current room',()=>{
  const {api}=load();
  for(const [room,activity,kind] of [['kitchen','做早餐','stove'],['master','午睡','bed'],
    ['study','处理工作邮件','chair'],['living','追剧','sofa']]){
    const p=api.pickRoomSpot(room,1,activity),items=api.SPRITES[room].filter(it=>it.kind===kind);
    assert.ok(items.some(item=>p.x>=item.x-12 && p.x<=item.x+item.w+12 &&
      p.y>=item.y-2 && p.y<=item.y+item.h+34),room+' aligns with furniture');
  }
});

test('eating and exercise never get the cooking-pan pose',()=>{
  const {api}=load();
  assert.equal(api.pickPose({activity:'做早餐'},false,false),'cooking');
  assert.equal(api.pickPose({activity:'吃早餐'},false,false),'eating');
  assert.equal(api.pickPose({activity:'健身'},false,false),'exercise');
  assert.equal(api.pickPose({activity:'睡觉'},false,false),'sleeping');
});

test('resident identity stays recognizable across mood changes',()=>{
  const {api}=load();assert.equal(typeof api.appearance,'function');
  const a=api.appearance({agent_id:1,age:32,gender:'女',mood:1});
  assert.deepEqual(a,api.appearance({agent_id:1,age:32,gender:'女',mood:-1}));
  assert.notDeepEqual(a,api.appearance({agent_id:2,age:32,gender:'男',mood:1}));
  assert.ok(Object.values(a).filter(v=>typeof v==='string').every(c=>/^#[a-f\d]{6}$/i.test(c)));
});

test('speech bubbles share the same canvas transform as furniture clicks',()=>{
  const {api}=load();api.state.sprites[1]={x:100,y:100};api._refreshGeometry();
  const anchor=api.bubbleAnchor(1),scale=960/api.CANVAS_W;
  assert.equal(anchor.x,8+100*scale);
  assert.ok(anchor.y>=0 && anchor.y<8+100*scale,'anchor is above the resident');
});

test('changing activity in the same room retargets the resident to its new facility',()=>{
  const {api}=load();const start=api.pickRoomSpot('kitchen',1,'吃早餐');
  api.state.session={residents:[{agent_id:1,room:'kitchen',activity:'做早餐'}]};
  api.state.sprites[1]={x:start.x,y:start.y,lastSpot:start,lastRoom:'kitchen',lastActivity:'吃早餐'};
  api.retargetSprites();
  assert.equal(api.state.sprites[1].isMoving,true);
  assert.notDeepEqual(api.state.sprites[1].lastSpot,start);
});


test('furniture stays within its room and remains selectable after relocation',()=>{
  const {api}=load(); api.state.session={residents:[]};
  for(const room of api.ROOMS) for(const it of api.SPRITES[room.id]) {
    assert.ok(it.x>=room.x && it.y>=room.y && it.x+it.w<=room.x+room.w && it.y+it.h<=room.y+room.h,room.id+it.kind);
    if(['stove','bed','tv','desk','tub'].includes(it.kind)) {
      const hit=api.hitTestFurniture(it.x+it.w/2,it.y+it.h/2);
      assert.equal(hit?.room.id,room.id);assert.equal(hit?.item.kind,it.kind);
    }
  }
});

test('walking around the living room avoids the sofa and coffee table',()=>{
  const {api}=load();
  const from={x:202,y:130},to={x:325,y:110};
  const route=[from,...api.roomWalkPath('living',from,to)];
  const obstacles=api.SPRITES.living.filter(it=>api.SOLID_FURNITURE.has(it.kind));
  for(let i=1;i<route.length;i++) {
    const a=route[i-1],b=route[i];
    const steps=Math.ceil(Math.hypot(b.x-a.x,b.y-a.y));
    for(let j=0;j<=steps;j++) {
      const x=a.x+(b.x-a.x)*j/steps,y=a.y+(b.y-a.y)*j/steps;
      assert.ok(!obstacles.some(it=>x>it.x && x<it.x+it.w && y>it.y && y<it.y+it.h),'walk crosses furniture');
    }
  }
});

test('window glazing is painted after the frame',()=>{
  const {api,ctx,calls}=load(); api.SPRITE_DRAW.window(ctx,{x:20,y:20,w:40,h:24});
  const frame=calls.findIndex(c=>c.key==='fillRect' && c.args[0]===18 && c.args[1]===18 && c.args[2]===44 && c.args[3]===28);
  const glass=calls.findIndex(c=>c.key==='fillRect' && c.color==='#b4d8e6');
  assert.ok(frame>=0 && glass>frame);
});

test('floor details and rugs are drawn before furniture, never over it',()=>{
  const {api,ctx,calls}=load(); api.paintApartment(ctx);
  const stove=api.SPRITES.kitchen.find(it=>it.kind==='stove');
  const stoveIndex=calls.findIndex(c=>c.key==='fillRect' && c.args[0]===stove.x && c.args[1]===stove.y && c.args[2]===stove.w);
  assert.ok(stoveIndex>0);
  const lateFloor=calls.slice(stoveIndex+1).find(c=>c.key==='fillRect' && c.args[0]===12 && c.args[1]===12 && c.args[2]===168 && c.args[3]===172);
  assert.equal(lateFloor,undefined);
});


test('four chatting residents and two study readers have separate spots',()=>{
  const {api}=load();
  api.state.session={residents:[1,2,3,4].map(agent_id=>({agent_id,room:'living',activity:'聊天'}))};
  const spots=api.state.session.residents.map(r=>api.pickRoomSpot(r.room,r.agent_id,r.activity));
  assert.equal(new Set(spots.map(p=>`${p.x},${p.y}`)).size,4);
  api.state.session={residents:[1,3].map(agent_id=>({agent_id,room:'study',activity:'看书'}))};
  const readers=api.state.session.residents.map(r=>api.pickRoomSpot(r.room,r.agent_id,r.activity));
  assert.notDeepEqual(readers[0],readers[1]);
});


test('six floor residents fit every semantic room and mixed poses share allocation',()=>{
  const {api}=load();
  for(const room of api.ROOMS) {
    api.state.session={residents:[1,2,3,4,5,6].map(agent_id=>({agent_id,room:room.id,activity:agent_id%2?'聊天':'瑜伽'}))};
    const spots=api.state.session.residents.map(r=>api.pickRoomSpot(r.room,r.agent_id,r.activity));
    assert.equal(new Set(spots.map(p=>`${p.x},${p.y}`)).size,6,room.id+' six separate positions');
    for(const p of spots) assert.ok(p.x>=room.x && p.x<=room.x+room.w && p.y>=room.y && p.y<=room.y+room.h,room.id+' inside room');
  }
});


test('a redirected walking resident routes from its physical room',()=>{
  const {api}=load();const start=api.pickRoomSpot('kitchen',1,'做早餐');
  api.state.session={residents:[{agent_id:1,room:'living',activity:'聊天'}]};
  api.state.sprites[1]={x:start.x,y:start.y,lastSpot:{x:570,y:150},lastRoom:'second',lastActivity:'看书',isMoving:true};
  api.retargetSprites();
  assert.ok(api.state.sprites[1].path.some(p=>p.x===api.ROOM_DOORS.kitchen.x && p.y===api.ROOM_DOORS.kitchen.y));
  assert.ok(!api.state.sprites[1].path.some(p=>p.x===api.ROOM_DOORS.second.x && p.y===api.ROOM_DOORS.second.y));
});
