from django.contrib import admin
from .models import Institution
from .models import Student
from .models import CourseTopic
from .models import CourseContent
from .models import CourseTopic1
from .models import CourseContent1
from .models import CourseTopic2
from .models import CourseContent2


admin.site.register(Institution)
admin.site.register(Student)
admin.site.register(CourseTopic)
admin.site.register(CourseContent)
admin.site.register(CourseTopic1)
admin.site.register(CourseContent1)
admin.site.register(CourseTopic2)
admin.site.register(CourseContent2)
