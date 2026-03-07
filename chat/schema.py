from drf_spectacular.extensions import OpenApiAuthenticationExtension


class OptionalJWTScheme(OpenApiAuthenticationExtension):
    target_class = "chat.authentication.OptionalJWTAuthentication"
    name = "optionalJwtAuth"

    def get_security_definition(self, auto_schema):
        return {
            "type": "http",
            "scheme": "bearer",
            "bearerFormat": "JWT",
        }
