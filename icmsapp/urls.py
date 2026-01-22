from django.urls import path
from . import views

urlpatterns = [
    # Auth / session
    path('', views.log, name='log'),
    path('logout/', views.user_logout, name='logout'),

    # Dashboards
    path('admindashboard/', views.admindashboard, name='admindashboard'),
    path('institutedashboard/', views.institutedashboard, name='institutedashboard'),
    path('studentdashboard/', views.studentdashboard, name='studentdashboard'),

    # Institution CRUD
    path('institution_list/', views.institution_list, name='institution_list'),
    path('add_institution/', views.add_institution, name='add_institution'),
    path('edit_institution/<int:pk>/', views.edit_institution, name='edit_institution'),
    path('delete/<int:pk>/', views.delete_institution, name='delete_institution'),
    path('api/institutes/count/', views.institution_count, name='institution_count'),

    # Students
    path('students/', views.student_list, name='student_list'),
    path('students/add/', views.student_add, name='student_add'),
    path('students/edit/<int:pk>/', views.student_add, name='student_edit'),
    path('students/delete/<int:pk>/', views.student_delete, name='student_delete'),
    path('students/edit-password/<int:pk>/', views.edit_password, name='edit_password'),

    # Static-ish
    path('goodsandservicetax/', views.goodsandservicetax, name='goodsandservicetax'),
    path('gov/', views.gov, name='gov'),
    path('gov1/', views.gov1, name='gov1'),

    # Courses
    path('course/', views.course_overview, name='course_overview'),
    path('course/topic/<int:topic_id>/', views.course_topic_detail, name='course_topic_detail'),
    path('course1/', views.course_overview1, name='course_overview1'),
    path('course1/topic/<int:topic_id>/', views.course_topic_detail1, name='course_topic_detail1'),

    # Registration
    path('register/', views.registration_step1, name='registration_step1'),
    path('register/verify/', views.registration_step2, name='registration_step2'),
    path('register/success/', views.registration_success, name='registration_success'),
    path('api/get-districts/', views.get_districts, name='get_districts'),
    path('api/resend-otp/', views.resend_otp, name='resend_otp'),

    # TRN + OTP
    path('trn/', views.trn_page, name='trn_page'),
    path('verify-otp/', views.verify_otp, name='verify_otp'),
    path('NIL_Return_Filinglog/', views.NIL_Return_Filinglog, name='NIL_Return_Filinglog'),

    # TRN Dashboard
    path('trn-dashboard/', views.trn_dashboard, name='trn_dashboard'),
    path('trn-dashboard/<int:content_id>/', views.trn_dashboard, name='trn_dashboard_with_id'),

    # GST Ledger Dashboard
    path('gst_ledger_dashboard/', views.gst_ledger_dashboard, name='gst_ledger_dashboard'),
    path('gst_ledger_dashboard/<int:content_id>/', views.gst_ledger_dashboard, name='gst_ledger_dashboard_with_id'),

    # File-Returns
    path('file-returns/', views.file_returns, name='file_returns'),
    path('file-returns/<int:content_id>/', views.file_returns, name='file_returns_with_id'),

    # JSON: basic
    path('api/course-content-basic/<int:pk>/', views.course_content_basic, name='course_content_basic'),

    # GSTR-1 + JSON Meta
    path('returns/gstr1/', views.gstr1_summary, name='gstr1_summary'),
    path('returns/gstr1/<int:content_id>/', views.gstr1_summary, name='gstr1_summary_with_id'),
    path('api/returns/gstr1/task/meta/', views.gstr1_task_meta, name='gstr1_task_meta_auto'),
    path('api/returns/gstr1/task/<int:content_id>/meta/', views.gstr1_task_meta, name='gstr1_task_meta_by_id'),
    path('gstdashboard/', views.gst_dashboard, name='gst_dashboard'),
    path('gstdashboard/<int:qid>/', views.gst_dashboard, name='gst_dashboard_with_id'),
    
  
    path("registration/<int:qid>/business/", views.step_business_details,name="step_business_details"),
    path("registration/<int:qid>/promoters/",views.step_promoters,name="step_promoters",),
    path("registration/<int:qid>/signatory/",views.step_authorized_signatory, name="step_authorized_signatory",),
    path("registration/<int:qid>/authorized-representative/",views.step_authorized_representative,name="step_authorized_representative",),
    path("registration/<int:qid>/principal-place/", views.step_principal_place,name="step_principal_place",),
    path("registration/<int:qid>/additional-places/", views.step_additional_places,name="step_additional_places",),
    path("registration/<int:qid>/goods-services/", views.step_goods_services, name="step_goods_services",),
    path("registration/<int:qid>/state-specific/", views.step_state_specific, name="step_state_specific",),
    path("registration/<int:qid>/aadhaar-authentication/", views.step_aadhaar, name="step_aadhaar",),
    path("registration/<int:qid>/verification/", views.step_verification, name="step_verification",),


    path('file-gstr1/', views.file_gstr1, name='file_gstr1'),
    path('returns/gstr1/file/<int:content_id>/', views.file_gstr1, name='file_gstr1'),

    path('gstr3b_return/', views.gstr3b_return, name='gstr3b_return'),
    path('returns/gstr3b/<int:content_id>/', views.gstr3b_return, name='gstr3b_return_with_id'),
    path('returns/gstr3b/filing/', views.file_gstr3b_view, name='file_gstr3b'),
    path('course2/', views.course_overview2, name='course_overview2'),
    path('course2/topic/<int:topic_id>/', views.course_topic_detail2, name='course_topic_detail2'),
    path('gov2/', views.gov2, name='gov2'),
    path('trn-dashboard1/', views.trn_dashboard1, name='trn_dashboard1'),
    path('trn-dashboard1/<int:content_id>/', views.trn_dashboard1, name='trn_dashboard1_with_id'),
    path('NIL_Return_Filinglog1/', views.NIL_Return_Filinglog1, name='NIL_Return_Filinglog1'),
    
    path('gst_ledger_dashboard1/', views.gst_ledger_dashboard1, name='gst_ledger_dashboard1'),

    path('file-returns1/', views.file_returns1, name='file_returns1'),

    path('returns1/gstr1/', views.gstr1_summary1, name='gstr1_summary1'),

    path('gstr_b2b_invoices/', views.gstr_b2b_invoices, name='gstr_b2b_invoices'),

    path('gstinvoiceform/', views.gstinvoiceform, name='gstinvoiceform'),

    path('invoice_listing/', views.invoice_listing, name='invoice_listing'),

    
]

    
