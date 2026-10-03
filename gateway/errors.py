class GatewayError(Exception):
    def __init__(self, status: int, code: str, message: str):
        self.status, self.code, self.message = status, code, message
        super().__init__(message)

    def payload(self):
        return {"error": {"message": self.message, "type": "gateway_error", "code": self.code}}
