const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync(__dirname + '/serious-game.js', 'utf8');
function fn(name, next, context) {vm.createContext(context); vm.runInContext(source.slice(source.indexOf('  function '+name+'('), source.indexOf('  function '+next+'(')), context);return context;}
test('round history follows chronological indexes', () => {
 const ctx=fn('historyBlock','currentBlock',{esc:String,t:(_,f)=>f,roleName:(_,r)=>r,actionLine:()=>'',session:null});
 const html=ctx.historyBlock({indicator_defs:[],rounds:[{index:0,title:'FIRST',actions:{},indicator_changes:{}},{index:1,title:'SECOND',actions:{},indicator_changes:{}}]});
 assert.ok(html.indexOf('FIRST') < html.indexOf('SECOND'));
});
test('debrief follows history and host controls are provided', () => {
 assert.ok(source.indexOf('historyBlock(session) : "")') < source.indexOf('+\n      debriefBlock(session)'));
 assert.match(source,/sgPause/); assert.match(source,/sgPreview/); assert.match(source,/decision:/);
});
