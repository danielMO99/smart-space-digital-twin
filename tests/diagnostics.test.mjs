import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import {model,history,poll,number,states} from '../frontend/js/diagnostics.mjs';
const examples=JSON.parse(fs.readFileSync(new URL('../docs/contracts/acquisition-diagnostics-v1.examples.json',import.meta.url)));
for(const e of examples)test(e.scenario,()=>{const m=model(e.response);assert.equal(m.state,e.response.acquisition.overall);assert.ok(m.title);});
test('All backend states, null, zero and modes',()=>{
 const d=structuredClone(examples[0].response);
 for(const state of Object.keys(states)){d.acquisition.overall=state;assert.equal(model(d).title,states[state]);}
 for(const source of ['simulation','live','replay']){d.acquisition.source=source;assert.ok(model(d).rows[0][1]);}
 d.acquisition.current_targets=0;assert.equal(model(d).rows.find(r=>r[0]==='Detecciones actuales')[1],'0');
 d.acquisition.current_targets=null;assert.equal(model(d).rows.find(r=>r[0]==='Detecciones actuales')[1],'Desconocidas');
 assert.equal(number(null),'No disponible');assert.equal(number(0,' Hz'),'0 Hz');
 d.acquisition.mode='legacy';assert.equal(history(d.acquisition).threshold,null);
 assert.throws(()=>model({schema_version:8}));
});
test('History preserves gaps, null, zero and 60 second bounds',()=>{
 const a={mode:'frames',sampled_monotonic_s:70,policy:{minimum_hz:8},history:[{monotonic_s:0,accepted_hz:3},{monotonic_s:10,accepted_hz:0},{monotonic_s:11,accepted_hz:null},{monotonic_s:12,accepted_hz:4},{monotonic_s:20,accepted_hz:4}]};
 const h=history(a);assert.equal(h.points.length,3);assert.equal(h.segments.length,3);assert.equal(h.points[0][1],150);assert.notEqual(h.threshold,null);
});
test('Polling serializes, recovers and cleans timers',async()=>{
 const timers=new Map();let id=0,calls=0,errors=0,received=0,resolve;
 const schedule=(fn,ms)=>{timers.set(++id,{fn,ms});return id;};const cancel=i=>timers.delete(i);
 const stop=poll({schedule,cancel,fetcher:()=>{calls++;return new Promise(r=>resolve=r);},onData:()=>received++,onError:()=>errors++});
 assert.equal(calls,1);assert.equal(timers.size,1);
 resolve({ok:false});await new Promise(r=>setImmediate(r));assert.equal(errors,1);assert.equal(timers.size,1);
 const [key,t]=[...timers][0];timers.delete(key);t.fn();assert.equal(calls,2);
 resolve({ok:true,json:async()=>examples[0].response});await new Promise(r=>setImmediate(r));assert.equal(received,1);assert.equal(timers.size,1);
 stop();assert.equal(timers.size,0);
});
test('Timeout never admits late normal response or starts parallel request',async()=>{
 const timers=new Map();let id=0,resolve,errors=0,received=0;
 const stop=poll({schedule:(fn,ms)=>{timers.set(++id,fn);return id;},cancel:i=>timers.delete(i),fetcher:()=>new Promise(r=>resolve=r),onData:()=>received++,onError:()=>errors++});
 [...timers.values()][0]();assert.equal(errors,1);
 resolve({ok:true,json:async()=>examples[0].response});await new Promise(r=>setImmediate(r));assert.equal(received,0);stop();assert.equal(timers.size,0);
});

test('Simulation unavailable branch and source counters remain distinct',()=>{
 const d=structuredClone(examples[0].response);
 d.acquisition.esp32.accumulated.offline_reports=63;d.acquisition.esp32.observed_increments.offline_reports=0;
 const m=model(d);assert.equal(m.a.esp32.accumulated.offline_reports,63);assert.equal(m.a.esp32.observed_increments.offline_reports,0);
 d.acquisition={schema_version:1,mode:'simulator',source:'simulation',overall:'unavailable',reasons:['no_mqtt_diagnostic_engine'],mqtt:null,freshness:null,frequency:null,integrity:null,esp32:null,session:null,history:[],current_targets:null};
 assert.equal(model(d).title,states.unavailable);assert.equal(history(d.acquisition).points.length,0);
});
test('Malformed JSON is a transport presentation failure, not old normal',async()=>{
 let failures=0;const timers=new Set();
 const stop=poll({fetcher:async()=>({ok:true,json:async()=>{throw SyntaxError('invalid JSON');}}),onData:()=>assert.fail('Must not show normal'),onError:()=>failures++,schedule:fn=>{timers.add(fn);return fn;},cancel:fn=>timers.delete(fn)});
 await new Promise(r=>setImmediate(r));assert.equal(failures,1);stop();assert.equal(timers.size,0);
});
