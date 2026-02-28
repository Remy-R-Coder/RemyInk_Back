from django.http import HttpResponse

class SuspensionMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.user.is_authenticated and request.user.is_suspended:
            return HttpResponse("Account suspended", status=403)
        return self.get_response(request)
