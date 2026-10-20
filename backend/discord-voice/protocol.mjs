export const MAX_LINE = 3000000;
const TYPES = new Set(['start','gateway','credit','stop','shutdown']);
export function decodeMessage(line) {
  if (Buffer.byteLength(line)>MAX_LINE) throw Error('ipc_size');
  const m=JSON.parse(line);
  if (!m || Array.isArray(m) || !TYPES.has(m.type)) throw Error('ipc_type');
  if (m.type!=='shutdown' && (!/^[a-zA-Z0-9-]{1,64}$/.test(m.session_id||'') || !/^[a-zA-Z0-9-]{1,64}$/.test(m.instance_id||''))) throw Error('ipc_session');
  if(m.type==='start' && ![m.guild_id,m.channel_id,m.user_id].every(x=>/^\d{1,32}$/.test(x))) throw Error('ipc_identity');
  if(m.type==='credit' && (!Number.isSafeInteger(m.sequence)||m.sequence<0)) throw Error('ipc_credit');
  return m;
}
