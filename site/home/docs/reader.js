'use strict';
const input=document.querySelector('#search');
const clear=document.querySelector('#clear');
const results=document.querySelector('#results');
const list=document.querySelector('#result-list');
const status=document.querySelector('#search-status');
const article=document.querySelector('#guide-body');
const more=document.querySelector('#more');
const directory=document.querySelector('#directory');
const navLinks=[...directory.querySelectorAll('a')];
const entries=[...article.querySelectorAll('[data-search]')].map(el=>({id:el.id,text:el.textContent.trim(),chapter:el.dataset.chapter}));
let matches=[],limit=40,terms=[];
if(matchMedia('(min-width:681px)').matches)directory.open=true;
function excerpt(text){const lower=text.toLocaleLowerCase();const positions=terms.map(t=>lower.indexOf(t)).filter(i=>i>=0);const first=positions.length?Math.min(...positions):0;const start=Math.max(0,first-55);return (start?'…':'')+text.slice(start,start+230)+(text.length>start+230?'…':'');}
function highlight(el,text){const pattern=new RegExp('('+terms.map(t=>t.replace(/[.*+?^${}()|[\]\\]/g,'\\$&')).join('|')+')','gi');let start=0;for(const match of text.matchAll(pattern)){el.append(document.createTextNode(text.slice(start,match.index)));const mark=document.createElement('mark');mark.textContent=match[0];el.append(mark);start=match.index+match[0].length;}el.append(document.createTextNode(text.slice(start)));}
function render(){list.replaceChildren();for(const item of matches.slice(0,limit)){const a=document.createElement('a');a.className='result';a.href='#'+item.id;const category=document.createElement('small');category.textContent=item.chapter;const p=document.createElement('p');highlight(p,excerpt(item.text));a.append(category,p);list.append(a);}status.textContent=matches.length?`找到 ${matches.length} 处匹配，当前显示 ${Math.min(limit,matches.length)} 处。`:'没有找到匹配内容。试试“模型”“访谈”或文件名中的关键词。';more.hidden=matches.length<=limit;}
function search(){const q=input.value.trim().slice(0,200);clear.hidden=!q;results.hidden=!q;article.hidden=!!q;terms=[...new Set(q.toLocaleLowerCase().split(/\s+/).filter(Boolean))];if(!q)return;limit=40;matches=entries.filter(e=>terms.every(t=>(e.text+' '+e.chapter).toLocaleLowerCase().includes(t)));render();}
function reset(focus=false){input.value='';search();if(focus)input.focus();}
input.addEventListener('input',search);clear.addEventListener('click',()=>reset(true));input.addEventListener('keydown',e=>{if(e.key==='Escape'){reset(true);e.preventDefault();}});document.querySelector('form').addEventListener('submit',e=>e.preventDefault());more.addEventListener('click',()=>{limit+=40;render();});
function followLink(e){const a=e.target.closest('a[href^="#"]');if(!a)return;reset();if(matchMedia('(max-width:680px)').matches)directory.open=false;const target=document.getElementById(a.hash.slice(1));if(target){e.preventDefault();history.pushState(null,'',a.hash);target.scrollIntoView({block:'start'});target.setAttribute('tabindex','-1');target.focus({preventScroll:true});}}
list.addEventListener('click',followLink);directory.addEventListener('click',followLink);
window.addEventListener('hashchange',()=>{reset();const el=document.getElementById(location.hash.slice(1));if(el)el.scrollIntoView();});
let scheduled=false;function updateActive(){scheduled=false;const chapters=[...article.querySelectorAll('.chapter')];let active=chapters[0]?.id;for(const c of chapters){if(c.getBoundingClientRect().top<=150)active=c.id;}for(const a of navLinks){if(a.hash==='#'+active)a.setAttribute('aria-current','location');else a.removeAttribute('aria-current');}}
window.addEventListener('scroll',()=>{if(!scheduled){scheduled=true;requestAnimationFrame(updateActive);}},{passive:true});updateActive();
