"""Read-only Telegram inbound signal adapter for captioned chart photos.

A user forwards an image WITH its caption (or plain text) to the EXISTING bot.
No private-group scraping, OCR, Telegram token handling or exchange orders.
Incoming chat is allowlisted; image is contextual only, and price levels come
from explicit user-supplied caption, never guessed from pixels.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime,timezone
from external_signal_validator import parse,validate_forwarded_text,MAX_LEN

MAX_FORWARD_AGE_S=6*3600
MAX_MSG_AGE_S=15*60
IMAGE_MIME={"image/jpeg","image/png","image/webp"}

def _source_age(msg, now_s):
    origin=msg.get("forward_origin")
    if not isinstance(origin,dict):
        return None
    d=origin.get("date")
    return (now_s-d) if type(d) is int else None

def _direction_hint_from_levels(caption):
    """Only a NON-actionable hint from price-level geometry.

    If LONG makes sense and SHORT does not, report a tentative direction.
    The sender must explicitly confirm it before the setup can be analyzed.
    """
    if not isinstance(caption,str):
        return None
    candidates=[]
    for side in ("LONG","SHORT"):
        test=parse(caption+"\n"+side)
        if test.get("status")=="PARSED":
            candidates.append(side)
    return candidates[0] if len(candidates)==1 else None

def interpret(update, allowed_chat_ids, now_s=None):
    """Return NO TRADE review data. Does NOT send or update any messages."""
    now_s=int(time.time()) if now_s is None else int(now_s)
    base={"tradeExecutionEnabled":False,"telegramSendingEnabled":False,
          "imageReadByAI":False,"priceVerified":False}
    if not isinstance(update,dict) or type(update.get("update_id")) is not int:
        return {**base,"status":"REJECTED","reasons":["BAD_TELEGRAM_UPDATE"]}
    msg=update.get("message")
    if not isinstance(msg,dict):
        return {**base,"status":"REJECTED","reasons":["NOT_A_NEW_MESSAGE"]}
    chat=msg.get("chat")
    if not isinstance(chat,dict) or chat.get("type")!="private":
        return {**base,"status":"REJECTED","reasons":["PRIVATE_CHAT_ONLY"]}
    # No broad wildcard: never process a third-party's message.
    allowed={int(v) for v in allowed_chat_ids if str(v).lstrip("-").isdigit()}
    if not allowed or type(chat.get("id")) is not int or chat["id"] not in allowed:
        return {**base,"status":"REJECTED","reasons":["UNAUTHORIZED_CHAT"]}
    stamp=msg.get("date")
    if type(stamp) is not int or not 0<=now_s-stamp<=MAX_MSG_AGE_S:
        return {**base,"status":"REJECTED","reasons":["MESSAGE_TOO_OLD"]}
    source_age=_source_age(msg,now_s)
    if source_age is not None and (source_age<0 or source_age>MAX_FORWARD_AGE_S):
        return {**base,"status":"OLD_SOURCE","reasons":["FORWARDED_SIGNAL_TOO_OLD"],
                "sourceAgeMinutes":int(source_age/60)}
    photos=msg.get("photo")
    photo=bool(isinstance(photos,list) and photos and
               any(isinstance(p,dict) and isinstance(p.get("file_id"),str) for p in photos))
    doc=msg.get("document")
    document_photo=bool(isinstance(doc,dict) and
                        doc.get("mime_type") in IMAGE_MIME and isinstance(doc.get("file_id"),str))
    has_image=photo or document_photo
    caption=msg.get("caption") if has_image else msg.get("text")
    if not isinstance(caption,str) or not caption.strip():
        return {**base,"status":"NEEDS_CAPTION",
                "imageAttached":has_image,
                "reasons":["SEND_IMAGE_WITH_ENTRY_SL_TP_AND_DIRECTION"]}
    if len(caption)>MAX_LEN:
        return {**base,"status":"REJECTED","imageAttached":has_image,
                "reasons":["CAPTION_TOO_LONG"]}
    parsed=parse(caption)
    if parsed.get("status")=="INCOMPLETE" and parsed.get("errors")==["ONE_DIRECTION_REQUIRED"]:
        hint=_direction_hint_from_levels(caption)
        return {**base,"status":"NEEDS_DIRECTION_CONFIRMATION",
                "imageAttached":has_image,"directionHintUnverified":hint,
                "reasons":["LONG_SHORT_NOT_EXPLICIT_IN_CAPTION"],
                "warning":"Direction shown only in the chart has not been read."}
    if parsed.get("status")!="PARSED":
        return {**base,"status":"INCOMPLETE",
                "imageAttached":has_image,"reasons":parsed.get("errors",["UNRECOGNIZED_CAPTION"])}
    # Inbound adapter NEVER claims the market data was fetched or a trade is valid.
    review=validate_forwarded_text(caption)
    return {**base,"status":"REQUIRES_BINANCE_PRICE_CHECK",
            "imageAttached":has_image,"symbol":parsed["symbol"],
            "direction":parsed["direction"],
            "entryZone":[parsed["entryLow"],parsed["entryHigh"]],
            "stopBoundary":parsed["stopBoundary"],
            "stopIsThreshold":parsed["stopIsThreshold"],
            "takeProfit1":parsed["takeProfit1"],
            "preliminaryDecision":review["decision"],
            "sourceDateVerified":source_age is not None,
            "reasons":["CURRENT_BINANCE_USDM_PRICE_NOT_FETCHED"],
            "warning":"This is a user-forwarded group idea, not a verified executable setup."}

def format_reply(result):
    status=result.get("status")
    if status=="NEEDS_CAPTION":
        return ("📷 Gambar diterima. Mohon sertakan keterangan pair, LONG/SHORT, "
                "Entry, SL dan TP pada caption foto. Saya belum membaca harga dari gambar.")
    if status=="NEEDS_DIRECTION_CONFIRMATION":
        h=result.get("directionHintUnverified")
        extra=f" Berdasarkan urutan harga, arahnya mungkin {h}, tetapi belum dikonfirmasi." if h else ""
        return ("⚠️ Arah LONG/SHORT tidak tertulis di caption."+extra+
                " Tambahkan arah tersebut pada pesan, lalu kirim ulang. NO TRADE.")
    if status=="REQUIRES_BINANCE_PRICE_CHECK":
        lo,hi=result["entryZone"]
        return (f"🐋 VALIDASI AWAL — {result['symbol']} {result['direction']}\n"
                f"Entry: {lo:g}–{hi:g} | SL: {result['stopBoundary']:g} | "
                f"TP1: {result['takeProfit1']:g}\n"
                "⚪ PERLU CEK HARGA BINANCE FUTURES LIVE.\n"
                "Chart hanya referensi; belum diperiksa otomatis.\n"
                "Keputusan transaksi sepenuhnya pada Anda. Tidak ada auto-trade.")
    return "⚠️ Belum dapat divalidasi. Status: "+str(status)+" — NO TRADE."

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--allowed-chat-id",required=True,help="Numeric account allowlist")
    args=p.parse_args()
    try:
        data=json.loads(sys.stdin.read(100_000))
    except (json.JSONDecodeError,ValueError):
        raise SystemExit("INVALID_UPDATE_JSON")
    out=interpret(data,[args.allowed_chat_id])
    print(json.dumps({"result":out,"previewReply":format_reply(out)},
                     ensure_ascii=False,indent=2))
    # No HTTP, bot token, image download or exchange trading in this tool.

if __name__=="__main__":
    main()
