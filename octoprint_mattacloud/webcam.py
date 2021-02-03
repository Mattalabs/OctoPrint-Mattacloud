import json
import logging
import os
import platform
import threading
import time
import logging

try:
    import asyncio
    from aiohttp import web
    from aiortc import RTCPeerConnection, RTCSessionDescription
    from aiortc.contrib.media import MediaPlayer
except ImportError:
    pass

_logger = logging.getLogger("octoprint.plugins.mattacloud")

async def offer(request):
    params = await request.json()
    offer = RTCSessionDescription(sdp=params["sdp"], type=params["type"])
    pc = RTCPeerConnection()
    pcs.add(pc)

    @pc.on("iceconnectionstatechange")
    async def on_iceconnectionstatechange():
        if pc.iceConnectionState == "failed":
            await pc.close()
            pcs.discard(pc)
    options = {"framerate": params["framerate"], "video_size": params["video_size"]}
    if platform.system() == "Darwin":
        player = MediaPlayer("http://127.0.0.1:8080/?action=stream", options=options)
    else:
        player = MediaPlayer("http://127.0.0.1:8080/?action=stream", options=options)

    await pc.setRemoteDescription(offer)
    for t in pc.getTransceivers():
        if t.kind == "video" and player.video:
            pc.addTrack(player.video)

    answer = await pc.createAnswer()
    await pc.setLocalDescription(answer)

    return web.Response(
        content_type="application/json",
        text=json.dumps(
            {"sdp": pc.localDescription.sdp, "type": pc.localDescription.type}
        ),
    )


async def close(request):
    coros = [pc.close() for pc in pcs]
    await asyncio.gather(*coros)
    pcs.clear()
    return web.Response(
        content_type="application/json",
        text=json.dumps(
            {"status": "success"}
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
        self.app.on_shutdown.append(on_shutdown)
        self.app.router.add_post("/offer", offer)
        self.app.router.add_post("/close", close)
        self.runner = None

    async def start(self):
        port = 8888
        self.runner = web.AppRunner(self.app)
        await self.runner.setup()
        site = web.TCPSite(self.runner, '127.0.0.1', port, ssl_context=None)
        await site.start()
    
    async def stop(self):
        await self.runner.cleanup()

async def webrtc_server_async():
    webrtc = WebRTCServer()
    await webrtc.start()

def webrtc_loop(loop):
    loop.create_task(webrtc_server_async())
    loop.run_forever()