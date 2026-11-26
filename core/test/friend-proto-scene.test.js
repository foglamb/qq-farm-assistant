const test = require('node:test');
const assert = require('node:assert/strict');
const { types, loadProto } = require('../src/utils/proto');

test('friend requests preserve farm and ranch scene IDs on the wire', async () => {
  await loadProto();
  const all = types.GetAllFriendsRequest.encode(types.GetAllFriendsRequest.create({ global_scene_id: 2 })).finish();
  assert.deepEqual([...all], [0x08, 0x02], 'ranch GetAll must encode field 1 instead of sending an empty request');
  assert.equal(types.GetAllFriendsRequest.decode(all).global_scene_id, 2);

  const selected = types.GetGameFriendsRequest.encode(types.GetGameFriendsRequest.create({ gids: [123], global_scene_id: 2 })).finish();
  const selectedDecoded = types.GetGameFriendsRequest.decode(selected);
  assert.equal(Number(selectedDecoded.gids[0]), 123);
  assert.equal(selectedDecoded.global_scene_id, 2);

  const sync = types.SyncAllFriendsRequest.encode(types.SyncAllFriendsRequest.create({ open_ids: ['friend-open-id'], global_scene_id: 2 })).finish();
  const syncDecoded = types.SyncAllFriendsRequest.decode(sync);
  assert.deepEqual(syncDecoded.open_ids, ['friend-open-id']);
  assert.equal(syncDecoded.global_scene_id, 2);
});
