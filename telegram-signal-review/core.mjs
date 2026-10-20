// Whale Intelligence Telegram signal caption parser (no OCR, no orders).
export function parseCaption(text){
  if(typeof text!=="string" || text.length>3000)return {status:"INVALID",errors:["CAPTION_INVALID"]};
  const pairs=[...new Set([...text.matchAll(/(?:\$|#)?([A-Z]{2,15})\s*(?:\/|[-_])?\s*USDT\b/gi)].map(m=>m[1].toUpperCase()+"USDT"))];
  const sides=[...new Set([...text.matchAll(/\b(LONG|SHORT)\b/gi)].map(m=>m[1].toUpperCase()))];
  const n="([0-9]+(?:[.,][0-9]+)?)",toN=s=>{const v=Number((s||"").replace(",","."));return Number.isFinite(v)&&v>0?v:null};
  const range=text.match(new RegExp("\\b(?:entry|entri|buy\\s+zone|sell\\s+zone|zona\\s+entry)\\b\\s*:?\\s*\\$?\\s*"+n+"\\s*(?:-|–|—|to|sampai)\\s*\\$?\\s*"+n,"i"));
  const single=text.match(new RegExp("\\b(?:entry|entri)\\b\\s*:?\\s*\\$?\\s*"+n,"i"));
  const sm=text.match(new RegExp("\\b(?:stop[\\s-]*loss|sl)\\b\\s*:?\\s*(below|under|di\\s+bawah|above|over|di\\s+atas|<|>)?\\s*\\$?\\s*"+n,"i"));
  const tm=text.match(new RegExp("\\b(?:take[\\s-]*profit|tp\\s*1?|target\\s*1?)\\b\\s*:?\\s*\\$?\\s*"+n,"i"));
  const low=range?Math.min(toN(range[1]),toN(range[2])):single?toN(single[1]):null;
  const high=range?Math.max(toN(range[1]),toN(range[2])):single?toN(single[1]):null;
  const stop=sm?toN(sm[2]):null,tp=tm?toN(tm[1]):null;
  const err=[];
  if(pairs.length!==1)err.push("PAIR_TIDAK_JELAS");
  if(sides.length!==1)err.push("ARAH_LONG_SHORT_BELUM_JELAS");
  if(low===null||high===null)err.push("ENTRY_TIDAK_JELAS");
  if(stop===null)err.push("SL_TIDAK_JELAS");
  if(tp===null)err.push("TP_TIDAK_JELAS");
  const hint=sides.length===0 && stop!==null&&low!==null&&tp!==null?
    stop<low&&tp>high?"LONG (butuh konfirmasi)":stop>high&&tp<low?"SHORT (butuh konfirmasi)":null:null;
  if(err.length)return {status:"INCOMPLETE",errors:err,hint};
  const side=sides[0],q=(sm?.[1]||"").toLowerCase().replace(/\s+/g," ");
  const bound=["below","under","di bawah","above","over","di atas","<",">"].includes(q);
  if(!(side==="LONG"?stop<low&&high<tp:tp<low&&high<stop))
    return {status:"INVALID",errors:["URUTAN_ENTRY_SL_TP_BERTENTANGAN"]};
  if(bound&&!(side==="LONG"?["below","under","di bawah","<"].includes(q):["above","over","di atas",">"].includes(q)))
    return {status:"INVALID",errors:["KETERANGAN_SL_BERTENTANGAN"]};
  return {status:"PARSED",symbol:pairs[0],side,low,high,stop,tp,stopIsBoundary:bound};
}
export function interpretUpdate(update,chatId,nowSec=Math.floor(Date.now()/1000)){
  const deny=(status,errors)=>({status,errors,autoTrade:false,tradeReady:false});
  if(!update||!Number.isSafeInteger(update.update_id))return deny("IGNORE",["INVALID_UPDATE"]);
  const msg=update.message;
  if(!msg||msg.chat?.type!=="private"||String(msg.chat.id)!==String(chatId))return deny("IGNORE",["PRIVATE_ALLOWLIST_ONLY"]);
  if(!Number.isSafeInteger(msg.date)||nowSec-msg.date<0||nowSec-msg.date>900)return deny("IGNORE",["MESSAGE_TOO_OLD"]);
  if(Number.isSafeInteger(msg.forward_origin?.date)&&(nowSec-msg.forward_origin.date>21600||nowSec-msg.forward_origin.date<0))
    return deny("STALE",["SOURCE_SIGNAL_TOO_OLD"]);
  const hasImage=(Array.isArray(msg.photo)&&msg.photo.length>0)||["image/jpeg","image/png","image/webp"].includes(msg.document?.mime_type);
  const caption=hasImage?msg.caption:msg.text;
  if(typeof caption!=="string"||!caption.trim())return {...deny("NEEDS_CAPTION",["CAPTION_REQUIRED"]),hasImage};
  const p=parseCaption(caption);
  return {status:p.status,errors:p.errors||[],parsed:p,hasImage,autoTrade:false,tradeReady:false};
}
export function assess(parsed,quote,nowMs=Date.now()){
  const base={autoTrade:false,tradeReady:false,tradeRecommendation:false};
  if(parsed?.status!=="PARSED")return {...base,decision:"DATA_TIDAK_LENGKAP"};
  if(!quote||quote.source!=="BINANCE_USDM_FUTURES"||quote.symbol!==parsed.symbol||
    !Number.isFinite(quote.price)||quote.price<=0||
    !Number.isSafeInteger(quote.atMs)||nowMs-quote.atMs<0||nowMs-quote.atMs>60000)
    return {...base,decision:"HARGA_BINANCE_BELUM_TERVERIFIKASI"};
  const sign=parsed.side==="LONG"?1:-1;
  const rr=(entry)=>{const risk=sign*(entry-parsed.stop),reward=sign*(parsed.tp-entry);
    return risk>0&&reward>0?Math.round(reward/risk*100)/100:null};
  const price=quote.price;
  const past=parsed.side==="LONG"?price>parsed.high:price<parsed.low;
  const ahead=parsed.side==="LONG"?price<parsed.low:price>parsed.high;
  return {...base,decision:past?"JANGAN_KEJAR_ENTRY":ahead?"TUNGGU_ENTRY":"DALAM_ZONA_PERLU_VERIFIKASI",
    currentPrice:price,rrLow:rr(parsed.low),rrHigh:rr(parsed.high)};
}
export function replyText(intake,review){
  if(intake.status==="IGNORE")return null;
  if(intake.status==="NEEDS_CAPTION")
    return "📷 Foto diterima. Kirim ulang dengan caption: PAIR, LONG/SHORT, ENTRY, SL, TP. Saya tidak menebak angka dari gambar.";
  if(intake.status==="STALE")return "⏰ Sinyal dari grup sudah terlalu lama. NO TRADE.";
  if(intake.status!=="PARSED")
    return "⚠️ Data sinyal belum lengkap: "+(intake.errors||[]).join(", ")+
      (intake.parsed?.hint?"\nPerkiraan arah: "+intake.parsed.hint:"")+
      "\nMohon konfirmasi data. Tidak ada rekomendasi transaksi.";
  const p=intake.parsed;
  const lines=["🐋 WHALE INTELLIGENCE — VALIDASI SINYAL GRUP",
    p.symbol+" "+p.side,
    "Entry: "+p.low+"–"+p.high+" | SL"+(p.stopIsBoundary?" batas":"")+": "+p.stop+" | TP1: "+p.tp,
    "Status: "+(review?.decision||"HARGA_BINANCE_BELUM_TERVERIFIKASI")];
  if(review?.currentPrice)lines.push("Mark Price Binance Futures: "+review.currentPrice);
  if(review?.rrLow!==undefined)lines.push("RR dengan asumsi SL batas: "+review.rrLow+"–"+review.rrHigh+" (sebelum biaya)");
  if(p.stopIsBoundary)lines.push("⚠️ SL under/above adalah batas, bukan harga stop pasti.");
  lines.push("Angka berasal dari caption; gambar belum dianalisis otomatis.");
  lines.push("Hanya bahan pertimbangan. Keputusan trading sepenuhnya pada Anda.");
  return lines.join("\n");
}
