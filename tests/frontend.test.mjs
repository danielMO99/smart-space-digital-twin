import test from 'node:test';
import assert from 'node:assert/strict';
import {project, signedSpeed, socketUrl, validFrame} from '../frontend/js/geometry.mjs';
test('Equal scale and Cartesian Y, including radar and opposite corners', () => {
  const room = {width_m:4,length_m:5};
  assert.deepEqual(project(0,0,room),[0,500]);
  assert.deepEqual(project(4,5,room),[400,0]);
  const radar = project(2,0.6,room);
  assert.equal(radar[0],200);
  assert.ok(Math.abs(radar[1]-440) < 1e-9);
  assert.deepEqual(project(1,1,room),[100,400]);
});
test('Radial speed preserves signs and units', () => {
  assert.equal(signedSpeed(-0.35),'−0.35 m/s');
  assert.equal(signedSpeed(0.35),'+0.35 m/s');
  assert.equal(signedSpeed(0),'+0.00 m/s');
});
test('WebSocket uses page host, port and TLS', () => {
  assert.equal(socketUrl(new URL('http://localhost:8000/')),'ws://localhost:8000/ws');
  assert.equal(socketUrl(new URL('https://example.org/')),'wss://example.org/ws');
});
test('Accept empty and three slots; reject malformed, duplicate and extra slots', () => {
  const frame = {schema_version:1,timestamp:'2026-10-24T12:00:00Z',targets:[]};
  const target = {slot:1,x_m:2,y_m:3,speed_m_s:-0.2,inside_room:true};
  assert.ok(validFrame(frame));
  assert.ok(validFrame({...frame, targets:[target,{...target,slot:2},{...target,slot:3}]}));
  for (const targets of [[target,target],[null],[{...target,x_m:Infinity}],[{...target,slot:4}]]) assert.equal(validFrame({...frame,targets}),false);
});
