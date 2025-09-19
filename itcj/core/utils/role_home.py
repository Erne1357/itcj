def role_home(role: str) -> str:
        return { "student": "/agendatec/student/home",
                 "coordinator": "/itcj/dashboard",
                 "social_service": "/itcj/dashboard",
                  "admin":"/itcj/dashboard" }.get(role, "/")