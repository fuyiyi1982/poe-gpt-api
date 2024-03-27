import toml
import os
import sys
import logging

import uvicorn
from fastapi import FastAPI, Request, WebSocket
from fastapi.responses import JSONResponse
import asyncio
from fastapi_poe.types import ProtocolMessage
from fastapi_poe.client import get_bot_response

file_path = os.path.abspath(sys.argv[0])
file_dir = os.path.dirname(file_path)
config_path = os.path.join(file_dir, "..", "config.toml")
config = toml.load(config_path)
proxy = config["proxy"]
timeout = config["api-timeout"] or config["timeout"] or 7

logging.basicConfig(level=logging.DEBUG)

app = FastAPI()

client_dict = {}

bot_names = {"Assistant", "ChatGPT-16k", "GPT-4", "GPT-4-128k", "Claude-3-Opus"}


async def get_responses(api_key, prompt, bot):
    if bot in bot_names:
        message = ProtocolMessage(role="user", content=prompt)
        buf = ""
        try:
            async for partial in get_bot_response(messages=[message], bot_name=bot, api_key=api_key):
                buf += partial.text
        except GeneratorExit:
            return buf
        return buf
    else:
        return "Not supported by this Model"


async def stream_get_responses(api_key, prompt, bot):
    if bot in bot_names:
        message = ProtocolMessage(role="user", content=prompt)
        try:
            async for partial in get_bot_response(messages=[message], bot_name=bot, api_key=api_key):
                yield partial.text
        except GeneratorExit:
            return
    else:
        yield "Not supported by this Model"


def add_token(token):
    if token not in client_dict:
        try:
            ret = asyncio.run(get_responses(token, "Please return “OK”", "Assistant"))
            if ret == "OK":
                client_dict[token] = token
                return "ok"
            else:
                return "failed"
        except Exception as exception:
            logging.info("Failed to connect to poe due to " + str(exception))
            return "failed: " + str(exception)
    else:
        return "exist"


@app.post("/add_token")
async def add_token_endpoint(token: str):
    return add_token(token)


@app.post("/ask")
async def ask(token: str, bot: str, content: str):
    add_token(token)
    try:
        return await get_responses(token, content, bot)
    except Exception as e:
        errmsg = f"An exception of type {type(e).__name__} occurred. Arguments: {e.args}"
        logging.info(errmsg)
        return JSONResponse(status_code=400, content={"message": errmsg})


@app.websocket("/stream")
async def websocket_endpoint(websocket: WebSocket):
    try:
        await websocket.accept()
        token = await websocket.receive_text()
        bot = await websocket.receive_text()
        content = await websocket.receive_text()
        add_token(token)
        async for ret in stream_get_responses(token, content, bot):
            await websocket.send_text(ret)
    except Exception as e:
        errmsg = f"An exception of type {type(e).__name__} occurred. Arguments: {e.args}"
        logging.info(errmsg)
        await websocket.send_text(errmsg)
    finally:
        await websocket.close()


if __name__ == '__main__':
    uvicorn.run(app, host="0.0.0.0", port=config.get('gateway-port', 5100))