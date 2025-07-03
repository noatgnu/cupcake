from django.http import JsonResponse


class XCupcakeInstanceIDMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        cupcake_id = request.headers.get('HTTP_X_CUPCAKE_INSTANCE_ID', None)
        if cupcake_id:
            response['cupcake-instance-id'] = cupcake_id
        return response

class InvalidateInactiveUserMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, 'user', None)
        if user and user.is_authenticated and not user.is_active:
            return JsonResponse({'detail': 'Account is inactive.'}, status=403)
        return self.get_response(request)