// Minimal Discord gateway for Mira Host: identifies the second bot and relays
// only what @discordjs/voice needs (voice state/server updates). It never reads
// messages; the existing PrimeFlow bot sends every text message.
const GATEWAY='wss://gateway.discord.gg/?v=10&encoding=json';
const INTENTS=(1<<0)|(1<<7); // GUILDS | GUILD_VOICE_STATES

export function createGateway({token,onDispatch,onReady,onClose,WebSocketImpl=globalThis.WebSocket,setTimer=setTimeout,clearTimer=clearTimeout}){
  let socket,sequence=null,heartbeat,acked=true,closed=false,userId=null,reconnects=0;
  const send=payload=>{if(socket?.readyState===1)socket.send(JSON.stringify(payload));};
  function beat(interval,first){
    heartbeat=setTimer(()=>{
      if(closed)return;
      if(!acked){socket?.close(4000,'zombie');return;}
      acked=false;send({op:1,d:sequence});beat(interval,false);
    },first?Math.floor(interval*Math.random()):interval);
  }
  function connect(){
    socket=new WebSocketImpl(GATEWAY);
    socket.onmessage=event=>{
      let message;try{message=JSON.parse(typeof event.data==='string'?event.data:Buffer.from(event.data).toString());}catch{return;}
      if(message.s!=null)sequence=message.s;
      if(message.op===10){
        acked=true;beat(message.d.heartbeat_interval,true);
        send({op:2,d:{token,intents:INTENTS,properties:{os:process.platform,browser:'primeflow-mira-host',device:'primeflow-mira-host'}}});
      }else if(message.op===11)acked=true;
      else if(message.op===1)send({op:1,d:sequence});
      else if(message.op===7||message.op===9)socket.close(4001,'reconnect');
      else if(message.op===0){
        if(message.t==='READY'){userId=message.d.user.id;reconnects=0;onReady?.(userId);}
        onDispatch?.(message.t,message.d);
      }
    };
    socket.onclose=event=>{
      clearTimer(heartbeat);
      if(closed)return;
      // 4004 is an invalid token: retrying would only be rate limited.
      if(event?.code===4004||event?.code===4014||++reconnects>5){closed=true;onClose?.(event?.code??0);return;}
      setTimer(connect,1000*reconnects);
    };
    socket.onerror=()=>{};
  }
  connect();
  return {
    get userId(){return userId;},
    // Only voice state updates (op 4) from @discordjs/voice are relayed.
    raw(payload){if(payload?.op===4)send({op:4,d:payload.d});},
    close(){closed=true;clearTimer(heartbeat);try{socket?.close(1000,'bye');}catch{}},
  };
}
