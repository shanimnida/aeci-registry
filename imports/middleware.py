from django.http import HttpResponse


class RegistrationRequestLimitMiddleware:
    """Bound public form bodies before Django parses multipart uploads/CSRF."""
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.path == "/register/" and request.method == "POST":
            try:
                too_large = int(request.META.get("CONTENT_LENGTH") or 0) > 65536
            except ValueError:
                too_large = True
            if too_large:
                return HttpResponse("This form submission is too large.", status=413, content_type="text/plain")
        return self.get_response(request)
