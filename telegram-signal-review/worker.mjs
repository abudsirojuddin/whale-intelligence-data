import {interpretUpdate,assess,replyText} from "./core.mjs";

const response=(body,status=200)=>new Response(body,{status});
const encoding=new TextEncoder();

async function telegram(env,method,payload){
  const r=await fetch("https://api.telegram.org/bot"+env.TELEGRAM_BOT_TOKEN+"/"+method,{
    method:"POST",headers:{"content-type":"application/json"},body:JSON.stringify(payload)});
  if(!r.ok)throw Error("Telegram "+r.status);
  const data=await r.json();
  if(!data.ok)throw Error("Telegram application response unsuccessful");
  return data;
}
async function markPrice(symbol){
  try{
    // Official Binance USD-M market data. HTTP 451/403 means NO PRICE,
    // never fall back to spot, another exchange or fabricated values.
    const ctrl=new AbortController(),timer=setTimeout(()=>ctrl.abort(),4500);
    try{
      const r=await fetch("https://fapi.binance.com/fapi/v1/premiumIndex?symbol="+encodeURIComponent(symbol),{
        signal:ctrl.signal,headers:{"accept":"application/json"}});
      if(!r.ok)return null;
      const json=await r.json();
      const price=Number(json.markPrice);
      if(json.symbol!==symbol||!Number.isFinite(price)||price<=0)return null;
      const observed=Number(json.time);
      if(!Number.isSafeInteger(observed)||Math.abs(Date.now()-observed)>60000)return null;
      return {source:"BINANCE_USDM_FUTURES",symbol,price,atMs:observed};
    }finally{clearTimeout(timer)}
  }catch(_){return null}
}
export default {
  async fetch(request,env){
    const url=new URL(request.url);
    if(url.pathname==="/health"&&request.method==="GET")
      return response(JSON.stringify({service:"whale-telegram-review",mode:"READ_ONLY",status:"READY_FOR_CONFIGURATION",autoTrade:false}),200);
    if(url.pathname!=="/webhook"||request.method!=="POST")return response("Not found",404);
    if(!env.TELEGRAM_WEBHOOK_SECRET||!env.TELEGRAM_CHAT_ID||!env.TELEGRAM_BOT_TOKEN||!env.DB)
      return response("Webhook unavailable",503);
    const header=request.headers.get("X-Telegram-Bot-Api-Secret-Token")||"";
    const good=encoding.encode(env.TELEGRAM_WEBHOOK_SECRET);
    const got=encoding.encode(header);
    if(got.length!==good.length||good.length<16)return response("Unauthorized",401);
    let matched=0;for(let i=0;i<got.length;i++)matched|=got[i]^good[i];
    if(matched!==0)return response("Unauthorized",401);
    if(Number(request.headers.get("content-length")||"0")>100000)return response("Too large",413);
    let update;
    try{update=await request.json()}catch(_){return response("Invalid JSON",400)}
    if(!Number.isSafeInteger(update?.update_id))return response("Invalid update",400);
    const intake=interpretUpdate(update,env.TELEGRAM_CHAT_ID);
    if(intake.status==="IGNORE")return response("OK");
    // UNIQUE constraint prevents duplicate delivery when Telegram retries the update.
    // Insert first, then process; never send repeated replies on uncertain network state.
    try{
      const inserted=await env.DB.prepare(
        "INSERT OR IGNORE INTO telegram_review_updates (update_id,received_at) VALUES (?,?)"
      ).bind(update.update_id,Math.floor(Date.now()/1000)).run();
      if(!inserted.meta?.changes)return response("OK");
    }catch(_){return response("Database unavailable",503)}
    const quote=intake.status==="PARSED"?await markPrice(intake.parsed.symbol):null;
    const review=assess(intake.parsed,quote);
    const text=replyText(intake,review);
    if(text){
      try{
        await telegram(env,"sendMessage",{chat_id:String(env.TELEGRAM_CHAT_ID),
          text,reply_parameters:{message_id:update.message.message_id,allow_sending_without_reply:true},
          disable_web_page_preview:true});
      }catch(_){
        // Return 200: do not cause Telegram retries that might duplicate messages.
        // Operators can inspect D1 update_id for a delivery uncertainty.
      }
    }
    return response("OK");
  }
};
