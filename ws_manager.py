class ConnectionManager:
    def __init__(self):
        self.active_connections = []

    async def connect(self, websocket, user_id=None):
        await websocket.accept()
        self.active_connections.append({"ws": websocket, "user_id": user_id})

    def disconnect(self, websocket):
        self.active_connections = [c for c in self.active_connections if c["ws"] != websocket]

    async def broadcast(self, message: dict):
        for conn in self.active_connections:
            try:
                await conn["ws"].send_json(message)
            except:
                pass

manager = ConnectionManager()