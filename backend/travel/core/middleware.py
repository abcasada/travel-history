from django.db import transaction

from .rls import set_context


class RlsContextMiddleware:
    """Wraps each request in a transaction carrying the RLS user context.

    Must sit after SessionMiddleware and replace AuthenticationMiddleware's position: it seeds
    `app.user_id` from the session so the user row itself is readable, resolves `request.user`,
    then re-sets the context to the resolved user (or clears it for anonymous/inactive users).

    Responses are fully rendered inside the transaction. Streaming responses must not query the
    database while streaming (they would run without a context and see nothing).
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        from django.contrib.auth import get_user

        session_uid = request.session.get("_auth_user_id")
        with transaction.atomic():
            set_context(int(session_uid) if session_uid else None)
            user = get_user(request)
            request.user = user
            set_context(user.pk if user.is_authenticated else None)
            response = self.get_response(request)
            if hasattr(response, "render") and callable(response.render):
                response = response.render()
        return response
