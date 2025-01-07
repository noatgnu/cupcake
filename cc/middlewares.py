class XCupcakeInstanceIDMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        cupcake_id = request.headers.get('HTTP_X_CUPCAKE_INSTANCE_ID', None)
        if cupcake_id:
            response['cupcake-instance-id'] = cupcake_id
        return response

