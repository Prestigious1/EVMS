import os
import django
from django.contrib.auth import authenticate, get_user_model

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'hms_prj.settings')
django.setup()

User = get_user_model()
username = 'alliakinkunmi1'
email = 'alliakinkunmi1@gmail.com'
password = '12121212@1'

user = authenticate(username=username, password=password)
print(f"User from authenticate(): {user}")
print(f"Exists in DB: {User.objects.filter(username=username).exists()}")

if user:
    print(f"Is Active: {user.is_active}")
    print(f"Is Staff: {user.is_staff}")
    print(f"Is Superuser: {user.is_superuser}")
    print(f"Role: {user.role}")
else:
    u = User.objects.get(username=username)
    print("User found but authentication failed!")
    print(f"Password Check: {u.check_password(password)}")
