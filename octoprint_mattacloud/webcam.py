import argparse
import asyncio
import json
import logging
import os
import platform
import ssl
import aiohttp_cors
import threading

import time
from aiohttp import web

from aiortc import RTCPeerConnection, RTCSessionDescription
from aiortc.contrib.media import MediaPlayer
import logging

_logger = logging.getLogger("octoprint.plugins.mattacloud")

ROOT = os.path.dirname(__file__)

async def index(request):
    content = open(os.path.join(ROOT, "index.html"), "r").read()
    return web.Response(content_type="text/html", text=content)


async def javascript(request):
    content = open(os.path.join(ROOT, "client.js"), "r").read()
    return web.Response(content_type="application/javascript", text=content)


async def offer(request):
    params = await request.json()
    offer = RTCSessionDescription(sdp=params["sdp"], type=params["type"])
    print(request)
    pc = RTCPeerConnection()
    pcs.add(pc)

    @pc.on("iceconnectionstatechange")
    async def on_iceconnectionstatechange():
        print("ICE connection state is %s" % pc.iceConnectionState)
        print(request)
        if pc.iceConnectionState == "failed":
            await pc.close()
            pcs.discard(pc)

    options = {"framerate": "5", "video_size": "640x360"}
    if platform.system() == "Darwin":
        player = MediaPlayer("default:none", format="avfoundation", options=options)
    else:
        player = MediaPlayer("/dev/video0", format="v4l2", options=options)

    await pc.setRemoteDescription(offer)
    for t in pc.getTransceivers():
        if t.kind == "audio" and player.audio:
            pc.addTrack(player.audio)
        elif t.kind == "video" and player.video:
            pc.addTrack(player.video)

    answer = await pc.createAnswer()
    await pc.setLocalDescription(answer)

    return web.Response(
        content_type="application/json",
        text=json.dumps(
            {"sdp": pc.localDescription.sdp, "type": pc.localDescription.type}
        ),
    )


pcs = set()


async def on_shutdown(app):
    # close peer connections
    coros = [pc.close() for pc in pcs]
    await asyncio.gather(*coros)
    pcs.clear()

class WebRTCServer:

    def __init__(self):
        self.app = web.Application()
        self.cors = aiohttp_cors.setup(self.app)    
        self.app.on_shutdown.append(on_shutdown)
        self.app.router.add_get("/webrtc", index)
        self.app.router.add_get("/client.js", javascript)
        self.cors.add(self.app.router.add_post("/offer",offer), {"*": aiohttp_cors.ResourceOptions(allow_methods=["POST"],allow_credentials=True, expose_headers="*",allow_headers="*",)})
        self.runner = None
        self.ssl_context = None

    async def start(self):
        port = 8888
        self.runner = web.AppRunner(self.app)
        await self.runner.setup()
        site = web.TCPSite(self.runner, '0.0.0.0', port,
                           ssl_context=self.ssl_context)
        await site.start()
    
    async def stop(self):
        await self.runner.cleanup()

async def webrtc_server_async():
    webrtc = WebRTCServer()
    await webrtc.start()

def webrtc_loop(loop):
    loop.create_task(webrtc_server_async())
    loop.run_forever()

def main():
    parser = argparse.ArgumentParser(description="WebRTC webcam demo")
    parser.add_argument("--cert-file", help="SSL certificate file (for HTTPS)")
    parser.add_argument("--key-file", help="SSL key file (for HTTPS)")
    parser.add_argument("--play-from", help="Read the media from a file and sent it."),
    parser.add_argument(
        "--host", default="0.0.0.0", help="Host for HTTP server (default: 0.0.0.0)"
    )
    parser.add_argument(
        "--port", type=int, default=8888, help="Port for HTTP server (default: 8080)"
    )
    parser.add_argument("--verbose", "-v", action="count")
    args = parser.parse_args()

    if args.verbose:
        logging.basicConfig(level=logging.DEBUG)

    if args.cert_file:
        ssl_context = ssl.SSLContext()
        ssl_context.load_cert_chain(args.cert_file, args.key_file)
    else:
        ssl_context = None

    app = web.Application()
    cors = aiohttp_cors.setup(app)    
    app.on_shutdown.append(on_shutdown)
    app.router.add_get("/", index)
    app.router.add_get("/client.js", javascript)
    cors.add(app.router.add_post("/offer",offer), {"*": aiohttp_cors.ResourceOptions(allow_methods=["POST"],allow_credentials=True, expose_headers="*",allow_headers="*",)})   
    web.run_app(app, host=args.host, port=args.port, ssl_context=ssl_context)

if __name__ == "__main__":
    main()