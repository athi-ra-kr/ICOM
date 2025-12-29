from django.shortcuts import render, redirect, get_object_or_404
from django.http import JsonResponse, Http404
from django.utils.dateparse import parse_date
from django.core.paginator import Paginator
from django.contrib import messages
from django.views.decorators.http import require_POST, require_GET
from django.views.decorators.csrf import csrf_exempt
from django.contrib.auth import logout
from django.db.models import Q
import json
import re
from datetime import date, datetime, timedelta

from .models import (
    Institution, Student,
    CourseTopic, CourseContent,
    CourseTopic1, CourseContent1
)

# =====================================================
# ============== COMPANY / TRADE NAME EXTRACT =========
# =====================================================

_COMPANY_SUFFIXES = (
    r"(?:Infotech|Technologies|Technology|Enterprises?|Associates|Agencies|Solutions?|Systems?|Labs?|"
    r"Industr(?:y|ies)|International|Corporation|Corp\.?|Ltd\.?|Limited|Pvt\.?\s*Ltd\.?|LLP|Company|Enterprizes)"
)
_HONORIFICS = r"(?:Mr|Mrs|Ms|Miss|Dr|Shri|Smt|Sri)\.?"
_HONORIFICS_SET = {"Mr", "Mrs", "Ms", "Miss", "Dr", "Shri", "Smt", "Sri"}

OWNER_PAT = re.compile(
    r"""(?im)
        \b(?:owner|proprietor|proprietrix|partner|director|managing\s+partner)
        \s*(?:name)?\s*[:=\-–—]\s*
        ([A-Z][A-Za-z .'\-]{1,80})
    """,
)

_BUSINESS_TOKENS = {
    "World","Stores","Store","Shop","Shops","Traders","Trader","Dealers","Dealer","Enterprises","Enterprise",
    "Associates","Agency","Agencies","Electronics","Electricals","Solutions","Systems","Technologies",
    "Technology","Industries","Industry","International","Corporation","Company","Corp","Labs","Ltd","LLP",
    "Pvt","Private","Limited","Enterprizes","Group","Mart","Bazaar","Center","Centre","Supermarket",
    "Mega","Hyper","Retail","Wholesale","Wholesalers","Wholesaler","Distributors","Distributor","Logistics",
    "Foods","Food","Cafe","Café","Restaurant","Builders","Constructions","Construction","Interio","Designs",
    "Design","Studios","Studio","Marketing","Services","Service"
}

def _looks_like_person(cand: str) -> bool:
    cand = (cand or "").strip()
    if not cand:
        return False

    tokens = cand.split()

    # reject if it's only an honorific (with/without dot), e.g., "Mr."
    if len(tokens) == 1:
        t0 = tokens[0].rstrip(".")
        if t0 in _HONORIFICS_SET:
            return False

    # if it starts with an honorific, require at least two tokens (e.g., "Mr John")
    if tokens:
        first = tokens[0].rstrip(".")
        if first in _HONORIFICS_SET and len(tokens) < 2:
            return False

    if not (1 <= len(tokens) <= 4):
        return False

    for t in tokens:
        # allow initials like "A." or "K."
        if t.endswith(".") and len(t) <= 3 and t[:-1].isalpha() and t[0].isupper():
            continue
        if not (t[0].isupper() and t[1:].islower()):
            return False
        if any(ch.isdigit() or ch in "@_-/&" for ch in t):
            return False
        if t in _BUSINESS_TOKENS:
            return False

    return True

_DATEY_TAIL = re.compile(
    r"""(?ix)
        (?:\s*,?\s*(?:on|since|from|in|as\s+of|established|started|commenced)\b.*$
          |\s*,?\s*(?:\d{1,2}\s*(?:st|nd|rd|th)?\s+[A-Za-z]{3,9}\s*,?\s*\d{2,4}).*$
          |\s*,?\s*(?:[A-Za-z]{3,9}\s+\d{1,2},?\s*\d{2,4}).*$
          |\s*,?\s*(?:\d{1,2}[/-]\d{1,2}[/-]\d{2,4}).*$
          |\s*,?\s*(?:\d{4}).*$
        )
    """
)

def _strip_quotes(s: str) -> str:
    s = (s or "").strip()
    if (len(s) >= 2) and ((s[0] == s[-1]) and s[0] in ("'", '"')):
        return s[1:-1].strip()
    return s

def _clean_company(s: str) -> str:
    s = (s or "").strip(" -–—:.,'•\t\r\n")
    s = _DATEY_TAIL.sub("", s)
    return s.strip(" -–—:.,'•\t\r\n")

def _looks_like_company(cand: str) -> bool:
    c = (cand or "").strip()
    if not c:
        return False
    if _looks_like_person(c):
        return False
    if re.search(rf"\b{_COMPANY_SUFFIXES}\b", c):
        return True
    parts = set(p.strip(" .,&-") for p in c.split())
    if parts & _BUSINESS_TOKENS:
        return True
    words = c.split()
    if len(words) >= 2 and all(w and w[0].isupper() for w in words[:2]):
        return True
    return False

def _extract_company_name(task_info: str, heading: str, topic_title: str) -> str:
    text = (task_info or "")
    text = re.sub(r"(?im)^(?:User\s*ID|Password|GSTIN|Email|Mobile|PAN)\s*[:=].*$", "", text)
    text = re.sub(r"[ \t]+", " ", text).strip()
    joined = text

    m = re.search(r"(?im)\b(Trade|Business)\s*Name\b\s*[:=\-–—]\s*(.+)$", joined)
    if m:
        cand = _strip_quotes(_clean_company(m.group(2)))
        if _looks_like_company(cand):
            return cand

    m = re.search(
        rf"""(?ix)
            \b(?:company|firm|business|shop)?\s*
            (?:named|called|trading\s+as|doing\s+business\s+as|d[/]b[/]a)\s*
            ["']?([A-Z][A-Za-z0-9& .'\-]{{1,100}})["']?
        """,
        joined
    )
    if m:
        cand = _strip_quotes(_clean_company(m.group(1)))
        if _looks_like_company(cand):
            return cand

    m = re.search(
        r"""(?ix)
            ^\s*
            (?!""" + _HONORIFICS + r"""\b)
            ([A-Z][\w&.'-]+(?:\s+[A-Z][\w&.'-]+){0,6})
            \s+(?:is|was|has|have|operates|operated|runs|owned|registered)\b
        """,
        joined
    )
    if m:
        cand = _clean_company(m.group(1))
        if _looks_like_company(cand):
            return cand

    for src in (heading or "", topic_title or ""):
        if src:
            mh = re.search(rf"\b([A-Z][A-Za-z0-9& .'\-]{{2,100}})\b", src)
            if mh:
                cand = _clean_company(mh.group(1))
                if _looks_like_company(cand):
                    return cand

    return "User"

# === NEW: extract legal name from first line (don't split on ".") ===
def _extract_legal_from_leading(task_info: str) -> str:
    t = (task_info or "").strip()
    if not t:
        return ""
    first_line = re.split(r"[\r\n]", t, maxsplit=1)[0].strip()

    m = re.match(
        rf"^\s*{_HONORIFICS}\s+([A-Z][A-Za-z.'-]+(?:\s+[A-Z][A-Za-z.'-]+){{0,3}})\b",
        first_line
    )
    if m:
        cand = m.group(1).strip()
        return cand if _looks_like_person(cand) else ""

    m2 = re.match(r"^\s*([A-Z][A-Za-z.'-]+(?:\s+[A-Z][A-Za-z.'-]+){0,3})\b", first_line)
    if m2:
        cand = m2.group(1).strip()
        return cand if _looks_like_person(cand) else ""

    return ""

# =====================================================
# ================== HELPERS / RESOLVER ===============
# =====================================================

def _resolve_task_id(request, content_id):
    cid = None
    if content_id is not None:
        try:
            cid = int(content_id)
        except (TypeError, ValueError):
            cid = None

    if cid is None:
        q = request.GET.get("content_id")
        if q and q.isdigit():
            cid = int(q)

    if cid is None:
        cid = request.session.get("last_content_id")

    if cid is None:
        ge2 = CourseContent1.objects.filter(id__gte=2).order_by("id").first()
        if ge2:
            cid = ge2.id
        else:
            first_any = CourseContent1.objects.order_by("id").first()
            if not first_any:
                raise Http404("No course content found.")
            cid = first_any.id

    if cid < 2 and CourseContent1.objects.filter(pk=2).exists():
        cid = 2

    if not CourseContent1.objects.filter(pk=cid).exists():
        ge2 = CourseContent1.objects.filter(id__gte=2).order_by("id").first()
        if ge2:
            cid = ge2.id
        else:
            first_any = CourseContent1.objects.order_by("id").first()
            if not first_any:
                raise Http404("No course content found.")
            cid = first_any.id

    return cid

def _company_for_task(content_id: int) -> str:
    obj = get_object_or_404(CourseContent1.objects.select_related("topic"), pk=content_id)
    heading = getattr(obj, "heading", "") or ""
    topic_title = obj.topic.title if getattr(obj, "topic_id", None) else ""
    task_info = getattr(obj, "task_info", "") or ""
    return _extract_company_name(task_info, heading, topic_title)

def _trade_name_for_task(content_id: int) -> str:
    return _company_for_task(content_id).upper()

# =====================================================
# =============== META PARSER & DUE DATES =============
# =====================================================

_DASH = r"[:=\-–—]"

def _norm(s: str) -> str:
    if not s:
        return ""
    s = s.replace("–", "-").replace("—", "-").replace("−", "-")
    return s.strip()

def _clean(v: str) -> str:
    return (v or "").strip(" \t\r\n-:=•").strip()

def _normalize_fy(y1: str, y2: str) -> str:
    try:
        a = int(y1)
    except:
        return f"{y1}-{y2}"
    if len(y2) == 2:
        try:
            tail = int(y2)
        except:
            return f"{y1}-{y2}"
        b = a // 100 * 100 + tail
        if b < a:
            b += 100
    else:
        try:
            b = int(y2)
        except:
            return f"{y1}-{y2}"
    return f"{a}-{b}"

MONTHS = {
    "jan":"January","january":"January","feb":"February","february":"February","mar":"March","march":"March",
    "apr":"April","april":"April","may":"May","jun":"June","june":"June","jul":"July","july":"July",
    "aug":"August","august":"August","sep":"September","sept":"September","september":"September",
    "oct":"October","october":"October","nov":"November","november":"November","dec":"December","december":"December",
}

def _fy_second_year(fy: str):
    m = re.match(r"^\s*([12]\d{3})\s*-\s*([12]\d{3})\s*$", fy or "")
    if not m:
        return None
    try:
        return int(m.group(2))
    except:
        return None

def _expand_year(two_or_four: str, fallback_year: int | None):
    try:
        n = int(two_or_four)
    except:
        return fallback_year
    if n >= 100:
        return n
    if fallback_year:
        century = (fallback_year // 100) * 100
        candidate = century + n
        if candidate < fallback_year - 20:
            candidate += 100
        return candidate
    return 2000 + n

def _return_period_to_month_year(return_period: str, fy: str | None):
    if not return_period:
        return None, None
    rp = return_period.strip()
    m = re.match(r"^([A-Za-z]{3,12})(?:[ '\-]?(\d{2,4}))?$", rp)
    if m:
        mon = MONTHS.get(m.group(1).lower(), m.group(1).title())
        year = None
        if m.group(2):
            year = _expand_year(m.group(2), _fy_second_year(fy) if fy else None)
        else:
            month_index = ["January","February","March","April","May","June","July","August","September","October","November","December"].index(mon)
            if fy:
                start_year = int(fy.split("-")[0])
                year = start_year if month_index >= 3 else start_year + 1
        return mon, year
    return None, None

def _compute_due_date_for_gstr1(month_name: str, year: int) -> date:
    months = ["January","February","March","April","May","June","July","August","September","October","November","December"]
    idx = months.index(month_name)
    next_idx = (idx + 1) % 12
    next_year = year + (1 if idx == 11 else 0)
    return date(next_year, next_idx + 1, 11)

def _compute_due_date_for_gstr3b(month_name: str, year: int) -> date:
    months = ["January","February","March","April","May","June","July","August","September","October","November","December"]
    idx = months.index(month_name)
    next_idx = (idx + 1) % 12
    next_year = year + (1 if idx == 11 else 0)
    return date(next_year, next_idx + 1, 21)

def parse_task_info_para(task_info: str):
    meta = {"GSTIN": "", "FY": "", "ReturnPeriod": "", "TradeName": "", "LegalName": ""}
    if not task_info:
        return meta

    text = _norm(task_info)
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    joined = "\n".join(lines)

    # FIRST: legal name from beginning (handles "Mr. ...")
    lead_name = _extract_legal_from_leading(joined)
    if lead_name:
        meta["LegalName"] = lead_name

    for ln in lines:
        m = re.search(rf"\bGSTIN\b\s*{_DASH}?\s*([0-9A-Z]{{15}})", ln, flags=re.I)
        if m and not meta["GSTIN"]:
            meta["GSTIN"] = m.group(1).upper(); continue
        m = re.search(
            rf"\b(FY|F\.?\s*Y\.?|F\s*Y|Fin(?:ancial)?\s*Y(?:r|ear)?)\b\s*{_DASH}?\s*\(?\s*([12]\d{{3}})\s*(?:[/\-]|\s+to\s+|\s+)([12]?\d{{2,4}})\)?",
            ln, flags=re.I
        )
        if m and not meta["FY"]:
            meta["FY"] = _normalize_fy(m.group(2), m.group(3)); continue
        m = re.search(
            rf"\b(Return\s*Period|Period|Month)\b\s*{_DASH}?\s*([A-Za-z]{{3,12}}(?:[ '\-]?\d{{2,4}})?|\d{{1,2}}[/\-]\d{{2,4}}|\d{{4}}[/\-]\d{{1,2}})",
            ln, flags=re.I
        )
        if m and not meta["ReturnPeriod"]:
            meta["ReturnPeriod"] = (m.group(2) or "").strip(" \t\r\n-:=•"); continue
        m = re.search(rf"\bTrade\s*Name\b\s*{_DASH}?\s*(.+)$", ln, flags=re.I)
        if m and not meta["TradeName"]:
            meta["TradeName"] = (m.group(1) or "").strip(" \t\r\n-:=•"); continue
        m = re.search(rf"\bLegal\s*Name\b\s*{_DASH}?\s*(.+)$", ln, flags=re.I)
        if m and not meta["LegalName"]:
            cand = (m.group(1) or "").strip()
            if _looks_like_person(cand):
                meta["LegalName"] = cand
            continue

    if not meta["GSTIN"]:
        m = re.search(rf"\bGSTIN\b\s*{_DASH}?\s*([0-9A-Z]{{15}})", joined, flags=re.I)
        if m: meta["GSTIN"] = m.group(1).upper()

    if not meta["FY"]:
        m = re.search(
            rf"\b(FY|F\.?\s*Y\.?|F\s*Y|Fin(?:ancial)?\s*Y(?:r|ear)?)\b\s*{_DASH}?\s*\(?\s*([12]\d{{3}})\s*(?:[/\-]|\s+to\s+|\s+)([12]?\d{{2,4}})\)?",
            joined, flags=re.I
        )
        if m: meta["FY"] = _normalize_fy(m.group(2), m.group(3))

    if not meta["ReturnPeriod"]:
        m = re.search(
            rf"\bReturn\s*Period\b\s*{_DASH}?\s*([A-Za-z]{{3,12}}(?:[ '\-]?\d{{2,4}})?|\d{{1,2}}[/\-]\d{{2,4}}|\d{{4}}[/\-]\d{{1,2}})",
            joined, flags=re.I
        ) or re.search(
            rf"\b(Period|Month)\b\s*{_DASH}?\s*([A-Za-z]{{3,12}}(?:[ '\-]?\d{{2,4}})?|\d{{1,2}}[/\-]\d{{2,4}}|\d{{4}}[/\-]\d{{1,2}})",
            joined, flags=re.I
        )
        if m: meta["ReturnPeriod"] = (m.group(m.lastindex) or "").strip(" \t\r\n-:=•")

    if not meta["LegalName"]:
        m_owner = OWNER_PAT.search(joined)
        if m_owner:
            cand = (m_owner.group(1) or "").strip()
            if _looks_like_person(cand): meta["LegalName"] = cand

    if not meta["LegalName"]:
        honor_pat = rf"\b{_HONORIFICS}\s+([A-Z][A-Za-z.'-]+(?:\s+[A-Z][A-Za-z.'-]+){{0,3}})"
        m = re.search(honor_pat, joined, flags=re.I)
        if m:
            cand = (m.group(1) or "").strip()
            if _looks_like_person(cand): meta["LegalName"] = cand

    if not meta["LegalName"]:
        m2 = re.search(
            r"""(?ix)
            ^\s*
            (?!""" + _HONORIFICS + r"""\b)
            ([A-Z][A-Za-z.'-]+(?:\s+[A-Z][A-Za-z.'-]+){0,3})
            \s+(?:started|commenced|requested|has\s+requested|is|was|has|have|asked|authorised|authorized|applied)\b
            """,
            joined
        )
        if m2:
            cand = (m2.group(1) or "").strip()
            if not re.search(rf"\b{_COMPANY_SUFFIXES}\b", cand) and _looks_like_person(cand):
                meta["LegalName"] = cand

    if not meta["TradeName"]:
        m = re.search(
            rf"""(?ix)
                \b(?:company|firm|business|shop)?\s*
                (?:named|called|trading\s+as|doing\s+business\s+as|d[/]b[/]a)\s*
                ["']?([A-Z][A-Za-z0-9& .'\-]{{1,100}})["']?
            """,
            joined
        )
        if m:
            cand = _strip_quotes(_clean_company(m.group(1)))
            if _looks_like_company(cand): meta["TradeName"] = cand

    if not meta["TradeName"]:
        m2 = re.search(
            r"""(?ix)
                ^\s*
                (?!""" + _HONORIFICS + r"""\b)
                ([A-Z][\w&.'-]+(?:\s+[A-Z][\w&.'-]+){0,6})
                \s+(?:is|was|has|have|operates|operated|runs|owned|registered)\b
            """,
            joined
        )
        if m2:
            cand = _clean_company(m2.group(1))
            if _looks_like_company(cand): meta["TradeName"] = cand

    mon, yr = _return_period_to_month_year(meta["ReturnPeriod"], meta["FY"])
    if mon and yr:
        meta["ReturnPeriod"] = f"{mon} {yr}"

    # uppercase Trade Name
    if meta["TradeName"]:
        meta["TradeName"] = meta["TradeName"].upper()

    return meta

def _format_date_ind(d: date) -> str:
    return d.strftime("%d %b %Y")

# ************ DEFAULT LEGAL NAME (UPPERCASE) ************
_LEGAL_NAME_DEFAULT = "AKHIL VASUDEV"

def _legal_name_for_task(content_id: int) -> str:
    obj = get_object_or_404(CourseContent1.objects.select_related("topic"), pk=content_id)
    meta = parse_task_info_para(obj.task_info or "")
    legal = (meta.get("LegalName") or "").strip()
    return legal if legal else _LEGAL_NAME_DEFAULT

# -------------------- Auth & Dashboards --------------------

def log(request):
    if request.method == 'POST':
        login_type = request.POST.get('loginType')
        email = request.POST.get('email')
        password = request.POST.get('password')

        if login_type == 'administrator':
            if email == 'icomvidya123@gmail.com' and password == 'icomvidya':
                request.session['user_type'] = 'admin'
                request.session['admin_name'] = 'Admin'
                return redirect('admindashboard')
            messages.error(request, "Invalid admin credentials")

        elif login_type == 'institute':
            try:
                institute = Institution.objects.get(email=email, password=password)
                request.session['user_type'] = 'institute'
                request.session['institution_id'] = institute.id
                request.session['institution_name'] = institute.name
                request.session['email'] = email
                return redirect('institutedashboard')
            except Institution.DoesNotExist:
                messages.error(request, "Invalid institution credentials")

        elif login_type == 'student':
            try:
                student = Student.objects.get(email=email, password=password)
                request.session['user_type'] = 'student'
                request.session['email'] = student.email
                request.session['student_name'] = student.name
                request.session['institution_name'] = student.institution.name
                return redirect('studentdashboard')
            except Student.DoesNotExist:
                messages.error(request, "Invalid student credentials")

    return render(request, 'log.html')

def admindashboard(request):
    if request.session.get('user_type') != 'admin':
        return redirect('log')
    institutions = Institution.objects.all()
    return render(request, 'admindashboard.html', {
        'admin_name': request.session.get('admin_name'),
        'institutions': institutions
    })

def get_logged_in_institution(request):
    institution_id = request.session.get('institution_id')
    if not institution_id:
        raise Exception("Institution ID not found in session.")
    return get_object_or_404(Institution, id=institution_id)

def institutedashboard(request):
    if request.session.get('user_type') != 'institute':
        return redirect('log')

    institution = get_logged_in_institution(request)

    if request.method == 'POST':
        student_name = request.POST.get('name')
        student_email = request.POST.get('email')
        student_id = request.POST.get('student_id')
        student_password = request.POST.get('password')

        if Student.objects.filter(email=student_email, institution=institution).exists():
            messages.error(request, "Email already exists.")
        elif Student.objects.filter(student_id=student_id, institution=institution).exists():
            messages.error(request, "Student ID already exists.")
        elif Student.objects.filter(institution=institution).count() >= institution.student_limit:
            messages.error(request, "Student limit reached.")
        else:
            Student.objects.create(
                institution=institution,
                name=student_name,
                email=student_email,
                student_id=student_id,
                password=student_password
            )
            messages.success(request, "Student added successfully.")
            return redirect('institutedashboard')

    students = Student.objects.filter(institution=institution)
    return render(request, 'institutedashboard.html', {
        'institution': institution,
        'students': students
    })

def studentdashboard(request):
    if request.session.get('user_type') != 'student':
        return redirect('log')
    return render(request, 'studentdashboard.html', {
        'student_name': request.session.get('student_name'),
        'institution_name': request.session.get('institution_name')
    })

# -------------------- Student CRUD --------------------

def student_list(request):
    institution = get_logged_in_institution(request)
    students_queryset = Student.objects.filter(institution=institution).order_by('id')
    paginator = Paginator(students_queryset, 8)
    page_number = request.GET.get('page')
    students_page = paginator.get_page(page_number)
    for student in students_page:
        student.masked_password = '*' * len(student.password)
    return render(request, 'student_list.html', {'students': students_page})

def student_add(request, pk=None):
    institution = get_logged_in_institution(request)
    student = get_object_or_404(Student, pk=pk, institution=institution) if pk else None

    if request.method == 'POST':
        name = request.POST.get('name')
        email = request.POST.get('email')
        student_id = request.POST.get('student_id')
        password = request.POST.get('password')

        email_qs = Student.objects.filter(email=email, institution=institution)
        if student:
            email_qs = email_qs.exclude(pk=student.pk)

        id_qs = Student.objects.filter(student_id=student_id, institution=institution)
        if student:
            id_qs = id_qs.exclude(pk=student.pk)

        if email_qs.exists():
            messages.error(request, "Email already exists in this institution.")
        elif id_qs.exists():
            messages.error(request, "Student ID already exists in this institution.")
        elif not student and Student.objects.filter(institution=institution).count() >= institution.student_limit:
            messages.error(request, "Student limit reached.")
        else:
            if student:
                student.name = name
                student.email = email
                student.student_id = student_id
                student.password = password
                student.save()
                messages.success(request, "Student updated successfully.")
            else:
                Student.objects.create(
                    institution=institution,
                    name=name, email=email,
                    student_id=student_id, password=password
                )
                messages.success(request, "Student added successfully.")
            return redirect('student_list')

    return render(request, 'student_form.html', {'student': student})

@require_POST
def edit_password(request, pk):
    institution = get_logged_in_institution(request)
    student = get_object_or_404(Student, pk=pk, institution=institution)
    new_password = (request.POST.get('password') or '').strip()
    if not new_password:
        return JsonResponse({'success': False, 'error': 'Password cannot be empty.'}, status=400)
    student.password = new_password
    student.save()
    return JsonResponse({'success': True})

def student_delete(request, pk):
    institution = get_logged_in_institution(request)
    student = get_object_or_404(Student, pk=pk, institution=institution)
    student.delete()
    messages.success(request, 'Student deleted successfully.')
    return redirect('student_list')

# -------------------- Institution CRUD --------------------

def institution_list(request):
    institutions = Institution.objects.all().order_by('-id')
    for inst in institutions:
        inst.masked_password = '*' * len(inst.password)
    paginator = Paginator(institutions, 8)
    page_number = request.GET.get("page")
    page_obj = paginator.get_page(page_number)
    return render(request, 'institution_list.html', {'page_obj': page_obj})

def add_institution(request):
    if request.method == 'POST':
        name = request.POST.get('name')
        email = request.POST.get('email')
        password = request.POST.get('password')
        student_limit = request.POST.get('student_limit')
        validity = request.POST.get('validity')

        if not all([name, email, password, student_limit, validity]):
            messages.error(request, "All fields are required.")
            return render(request, 'institution_form.html')

        try:
            student_limit = int(student_limit)
            validity = parse_date(validity)
            if Institution.objects.filter(email=email).exists():
                messages.error(request, "Email already exists.")
                return render(request, 'institution_form.html')

            Institution.create(
                name=name, email=email, password=password,
                student_limit=student_limit, validity=validity
            )
            messages.success(request, "Institution added successfully.")
            return redirect('institution_list')
        except Exception as e:
            messages.error(request, f"Error: {str(e)}")
            return render(request, 'institution_form.html')

    return render(request, 'institution_form.html')

def edit_institution(request, pk):
    institution = get_object_or_404(Institution, pk=pk)
    if request.method == 'POST':
        name = request.POST.get('name')
        email = request.POST.get('email')
        password = request.POST.get('password')
        student_limit = request.POST.get('student_limit')
        validity = parse_date(validity := request.POST.get('validity'))

        if not all([name, email, student_limit, validity]):
            messages.error(request, "All fields except password are required.")
            return render(request, 'institution_form.html', {'institution': institution})

        try:
            institution.name = name
            institution.email = email
            institution.student_limit = int(student_limit)
            institution.validity = validity
            if password:
                institution.password = password
            institution.save()
            messages.success(request, "Institution updated successfully.")
            return redirect('institution_list')
        except Exception as e:
            messages.error(request, f"Error: {str(e)}")
            return render(request, 'institution_form.html', {'institution': institution})

    return render(request, 'institution_form.html', {'institution': institution})

def delete_institution(request, pk):
    institution = get_object_or_404(Institution, pk=pk)
    if request.method == 'POST':
        institution.delete()
        messages.success(request, "Institution deleted successfully.")
    return redirect('institution_list')

def institution_count(request):
    count = Institution.objects.count()
    return JsonResponse({'count': count})

def user_logout(request):
    logout(request)
    return redirect('log')

def goodsandservicetax(request):
    return render(request, 'goodsandservicetax.html')

# -------------------- Courses --------------------

def course_overview(request):
    topics = CourseTopic.objects.order_by('order')
    selected_topic = topics.first()
    content = CourseContent.objects.filter(topic=selected_topic).first()
    previous_topic = next_topic = None
    if selected_topic:
        arr = list(topics)
        i = arr.index(selected_topic)
        previous_topic = arr[i - 1] if i > 0 else None
        next_topic = arr[i + 1] if i < len(arr) - 1 else None

    return render(request, 'course_overview.html', {
        'topics': topics, 'selected_topic': selected_topic, 'content': content,
        'previous_topic': previous_topic, 'next_topic': next_topic
    })

def course_topic_detail(request, topic_id):
    if request.session.get('user_type') != 'student':
        messages.error(request, "You must be logged in as a student.")
        return redirect('log')

    email = request.session.get('email')
    if not email:
        messages.error(request, "Student session missing. Please log in again.")
        return redirect('log')

    if not Student.objects.filter(email=email).exists():
        messages.error(request, "No student matches the given session.")
        return redirect('log')

    selected_topic = get_object_or_404(CourseTopic, id=topic_id)
    content = CourseContent.objects.filter(topic=selected_topic).first()
    topics = CourseTopic.objects.all().order_by('order')

    return render(request, 'course_overview.html', {
        'selected_topic': selected_topic, 'content': content, 'topics': topics,
    })

def gov(request):
    return render(request, 'gov.html')

def course_overview1(request):
    topics = list(CourseTopic1.objects.order_by('order'))
    selected_topic = topics[0] if topics else None
    content = CourseContent1.objects.filter(topic=selected_topic).first() if selected_topic else None
    previous_topic = next_topic = None
    if selected_topic:
        i = topics.index(selected_topic)
        previous_topic = topics[i - 1] if i > 0 else None
        next_topic = topics[i + 1] if i < len(topics) - 1 else None

    return render(request, 'course_overview1.html', {
        'topics': topics, 'selected_topic': selected_topic, 'content': content,
        'previous_topic': previous_topic, 'next_topic': next_topic,
    })

def course_topic_detail1(request, topic_id):
    topics = list(CourseTopic1.objects.order_by('order'))
    selected_topic = get_object_or_404(CourseTopic1, pk=topic_id)
    content = CourseContent1.objects.filter(topic=selected_topic).first()
    previous_topic = next_topic = None
    if selected_topic in topics:
        i = topics.index(selected_topic)
        previous_topic = topics[i - 1] if i > 0 else None
        next_topic = topics[i + 1] if i < len(topics) - 1 else None

    return render(request, 'course_overview1.html', {
        'topics': topics, 'selected_topic': selected_topic, 'content': content,
        'previous_topic': previous_topic, 'next_topic': next_topic,
    })

def gov1(request):
    return render(request, 'gov1.html')

# -------------------- Registration & TRN --------------------

STATES_DISTRICTS = {
    'Andhra Pradesh':['Anantapur', 'Chittoor' , 'East Godavari' , 'Krishna' , 'kurnool' , 'Nellore' , 'Prakasam' , 'Srikakulam' , 'Viskhapattanam' , 'Vizianagaram' , 'West Godavari' , 'YSR Kadapa'] ,
    'Arunachal Pradesh':['Tawng' ,'West Kameng' ,' East Kameng' , 'Papum Pare' ,'Kurung Kumey','Kra Daadi' , 'Lower Subansiri', 'Upper Subansiri' , 'West Siang' , 'East Siang' , 'Siang' , 'Upper Sing' , 'Lower Sing' ,'Dibing Valley' , 'Anjaw' , 'Lohit' ,'Namasai', 'Changlang' , 'Tirap' , 'Longding' ],
    'Assam':['Baksa' , 'Barpeta' , 'Biswanath' , 'Bongaigaon' , 'Cachar' , 'Charaideo' , 'Chirang' , 'Darrang' , 'Dhemaji' , 'Dhubri' , 'Dibrugarh' , 'Dima Hasao (formerly North Cachar Hills)' , 'Goalpara' , 'Golaghat' , 'Hailakandi' , 'Hojai' , 'Jorhat' , 'Kamrup' , 'Kamrup Metropolitan' , 'Karbi Anglong' , 'Karimganj' , 'Kokrajhar' , 'Lakhimpur' , 'Majuli ' , 'Morigaon' , 'Nagaon' , 'Nalbari' , 'Sivasagar' , 'onitpur' , 'South Salmara-Mankachar' , 'Tinsukia' , 'Udalguri' , 'West Karbi Anglong' , 'Tamulpur' , 'Bajali'],
    'Bihar':['Patna' , 'Nalanda' , 'Bhojpur' , 'Buxar' , 'Rohtas' , 'Muzaffarpur' , 'Vaishali' , 'Sitamarhi' , 'Sheohar' , 'East Champaran (Motihari)' , 'West Champaran (Bettiah)' , 'Darbhanga' , 'Madhubani' , 'Samastipur' , 'Saharsa' , 'Supaul' , 'Madhepura' , 'Purnia' , 'Araria' , 'Kishanganj' , 'Katihar' ,'Bhagalpur' , 'anka' , 'Munger' , 'Jamui' , 'Lakhisarai' , 'Sheikhpura' , 'GayaNawada' , 'Aurangabad' ,'Jehanabad', 'Arwal', 'Saran (Chhapra)', 'Siwan' , 'Gopalganj'],
    'Chhattisgarh':['Balod','Baloda Bazar','Balrampur','Bastar','Bemetara','Bijapur','Bilaspur','Dantewada (South Bastar)','Dhamtari','Durg','Gariaband','Gaurela-Pendra-Marwahi','Janjgir-Champa','Jashpur','Kabirdham (Kawardha)','Kanker (North Bastar)','Kondagaon','Korba','Koriya','Mahasamund','Mungeli','Narayanpur','Raigarh','Raipur','Rajnandgaon','Sukma','Surajpur','Surguja','Sarangarh-Bilaigarh','Khairagarh-Chhuikhadan-Gandai','Manendragarh-Chirmiri-Bharatpur','Mohla-Manpur-Ambagarh Chowki'],
    'Goa':['North Goa','South Goa'],
    'Gujarat':['Ahmedabad','Amreli','Anand','Aravalli','Banaskantha (Palanpur)','Bharuch','Bhavnagar','Botad','Chhota Udaipur', 'Dahod','Dang (Ahwa)','Devbhoomi Dwarka','Gandhinagar','Gir Somnath', 'Jamnagar','Junagadh','Kheda (Nadiad)','Kutch (Bhuj)','Mahisagar','Mehsana','Morbi','Narmada (Rajpipla)','Navsari','Panchmahal (Godhra)','Patan','Porbandar','Rajkot','Sabarkantha (Himmatnagar)','Surat','Surendranagar','Tapi (Vyara)','Vadodara','Valsad'],	
    'Haryana':['Ambala','Bhiwani','Charkhi Dadri','Faridabad','Fatehabad','Gurugram','Hisar','Jhajjar','Jind','Kaithal','Karnal','Kurukshetra','Mahendragarh','Nuh','Palwal','Panchkula','Panipat','Rewari','Rohtak','Sirsa','Sonipat','Yamunanagar'],	
    'Himachal Pradesh':['Bilaspur','Chamba','Hamirpur','Kangra','Kinnaur','Kullu','Lahaul and Spiti','Mandi','Shimla','Sirmaur','Solan','Una'],	
    'Jharkhand':['Bokaro','Chatra','Deoghar','Dhanbad', 'Dumka','East Singhbhum','Garhwa','Giridih','Godda','Gumla','Hazaribagh','Jamtara','Khunti','Koderma','Latehar','Lohardaga', 'Pakur','Palamu','Ramgarh','Ranchi','Sahebganj','Seraikela Kharsawan','Simdega','West Singhbhum'],
    'Karnataka': [ 'Bagalkot','Ballari','Belagavi','Bengaluru Rural','Bengaluru Urban','Bidar','Chamarajanagar','Chikballapur','Chikkamagaluru','Chitradurga','Dakshina Kannada','Davanagere','Dharwad','Gadag', 'Hassan','Haveri','Kalaburagi','Kodagu','Kolar','Koppal','Mandya','Mysuru','Raichur','Ramanagara','Shivamogga','Tumakuru', 'Udupi','Uttara Kannada','Vijayapura','Yadgir','Vijayanagara'],
    'Kerala': ['Alappuzha','Ernakulam','Idukki','Kannur','Kasaragod','Kollam','Kottayam','Kozhikode','Malappuram','Palakkad','Pathanamthitta','Thiruvananthapuram','Thrissur','Wayanad'],
    'Madhya Pradesh':['Agar Malwa','Alirajpur','Anuppur','Ashoknagar','Balaghat','Barwani','Betul','Bhind','Bhopal','Burhanpur','Chhatarpur','Chhindwara','Damoh','Datia','Dewas','Dhar','Dindori','Guna','Gwalior','Harda','Hoshangabad','Indore','Jabalpur','Jhabua','Katni','Khandwa','Khargone','Mandla','Mandsaur','Morena','Narsinghpur','Neemuch','Niwari','Panna','Raisen','Rajgarh','Ratlam','Rewa','Sagar','Satna','Sehore','Seoni','Shahdol','Shajapur','Sheopur','Shivpuri','Sidhi','Singrauli','Tikamgarh','Ujjain','Umaria','Vidisha'],
    'Maharashtra': ['Ahmednagar','Akola','Amravati','Aurangabad','Beed','Bhandara','Buldhana','Chandrapur','Dhule','Gadchiroli','Gondia','Hingoli','Jalgaon','Jalna','Kolhapur','Latur','Mumbai City','Mumbai Suburban','Nagpur','Nanded','Nandurbar','Nashik','Osmanabad','Palghar','Parbhani','Pune','Raigad','Ratnagiri','Sangli','Satara','Sindhudurg','Solapur','Thane','Wardha','Washim','Yavatmal'],
    'Manipur':['Bishnupur','Chandel','Churachandpur','Imphal East','Imphal West', 'Jiribam','Kakching','Kamjong','Kangpokpi','Noney', 'Pherzawl', 'Senapati','Tamenglong','Tengnoupal','Thoubal','Ukhrul'],	
    'Meghalaya':['East Garo Hills','East Jaintia Hills','East Khasi Hills','North Garo Hills','Ri Bhoi','South Garo Hills','South West Garo Hills','South West Khasi Hills','West Garo Hills','West Jaintia Hills','West Khasi Hills','South West Khasi Hills'],
    'Mizoram':['Aizawl','Champhai','Kolasib', 'Lawngtlai','Lunglei', 'Mamit','Saiha','Serchhip','Hnahthial','Saitual','Khawzawl'],	
    'Nagaland':[ 'Dimapur','Kiphire','Kohima','Longleng','Mokokchung','Mon','Peren','Phek','Tuensang','Wokha', 'Zunheboto','Noklak'],	
    'Odisha':['Angul','Balangir','Balasore','Bargarh','Bhadrak','Boudh','Cuttack','Deogarh','Dhenkanal','Gajapati','Ganjam', 'Jagatsinghpur', 'Jajpur', 'Jharsuguda', 'Kalahandi','Kandhamal','Kendrapara', 'Kendujhar (Keonjhar)','Khordha','Koraput','Malkangiri', 'Mayurbhanj', 'Nabarangpur',  'Nayagarh', 'Nuapada', 'Puri','Rayagada', 'Sambalpur', 'Sonepur','Sundergarh'],	
    'Punjab':['Amritsar','Barnala', 'Bathinda','Faridkot', 'Fatehgarh Sahib', 'Fazilka', 'Ferozepur', 'Gurdaspur','Hoshiarpur',  'Jalandhar', 'Kapurthala', 'Ludhiana','Mansa','Moga','Muktsar','Nawanshahr (Shahid Bhagat Singh Nagar)','Pathankot','Patiala','Rupnagar','Sangrur','SAS Nagar (Mohali)','Tarn Taran'],	
    'Rajasthan':['Ajmer', 'Alwar', 'Banswara', 'Baran', 'Barmer', 'Bharatpur', 'Bhilwara', 'Bikaner', 'Bundi', 'Chittorgarh', 'Churu', 'Dausa', 'Dholpur','Dungarpur','Hanumangarh','Jaipur','Jaisalmer','Jalore','Jhalawar','Jhunjhunu','Jodhpur', 'Karauli','Kota','Nagaur','Pali','Pratapgarh','Rajsamand','Sawai Madhopur', 'Sikar','Sirohi','Tonk','Udaipur'],
    'Sikkim':['East Sikkim','North Sikkim','South Sikkim','West Sikkim'],	
    'Tamil Nadu':['Ariyalur','Chennai','Coimbatore', 'Cuddalore', 'Dharmapuri', 'Dindigul', 'Erode', 'Kanchipuram', 'Kanyakumari', 'Karur',  'Krishnagiri',  'Madurai', 'Nagapattinam', 'Namakkal', 'Perambalur', 'Pudukkottai','Ramanathapuram', 'Salem',  'Sivaganga',  'Tenkasi', 'Thanjavur','The Nilgiris', 'Theni',  'Thoothukudi (Tuticorin)', 'Tiruchirappalli', 'Tirunelveli','Tirupur','Tiruvallur', 'Tiruvannamalai','Tiruvarur','Vellore', 'Viluppuram','Virudhunagar'],	
    'Telangana':['Adilabad','Bhadradri Kothagudem','Hyderabad','Jagtial','Jangaon','Jayashankar Bhoopalpally','Jogulamba Gadwal','Kamareddy','Karimnagar','Khammam','Komaram Bheem Asifabad','Mahabubabad','Mahbubnagar','Mancherial','Medak', 'Medchal-Malkajgiri', 'Mulugu','Nagarkurnool', 'Nalgonda','Narayanpet', 'Nirmal', 'Nizamabad','Peddapalli','Rajanna Sircilla', 'Rangareddy','Sangareddy','Siddipet','Suryapet','Vikarabad','Wanaparthy','Warangal Rural','Warangal Urban','Yadadri Bhuvanagiri'],
    'Tripura':['Dhalai', 'Gomati','Khowai', 'North Tripura', 'Sepahijala', 'South Tripura','Unakoti','West Tripura'],	
    'Uttar Pradesh':[ 'Agra','Aligarh','Ambedkar Nagar','Amethi','Amroha','Auraiya','Ayodhya','Azamgarh','Baghpat','Bahraich','Ballia','Balrampur','Banda','Barabanki','Bareilly','Basti','Bhadohi','Bijnor','Budaun','Bulandshahr','Chandauli','Chitrakoot','Deoria','Etah','Etawah','Farrukhabad','Fatehpur','Firozabad','Gautam Buddha Nagar','Ghaziabad', 'Ghazipur', 'Gonda', 'Gorakhpur','Hamirpur','Hapur','Hardoi','Hathras','Jalaun','Jaunpur','Jhansi','Kannauj','Kanpur Dehat','Kanpur Nagar','Kasganj','Kaushambi','Kushinagar','Lakhimpur Kheri','Lalitpur','Lucknow','Maharajganj', 'Mahoba','Mainpuri','Mathura','Mau','Meerut','Mirzapur', 'Moradabad','Muzaffarnagar','Pilibhit','Pratapgarh','Raebareli', 'Rampur', 'Saharanpur', 'Sambhal','Sant Kabir Nagar','Shahjahanpur', 'Shamli', 'Shravasti','Siddharthnagar', 'Sitapur', 'Sonbhadra', 'Sultanpur', 'Unnao','Varanasi'],	
    'Uttarakhand':['Almora','Bageshwar','Chamoli','Champawat','Dehradun', 'Haridwar','Nainital','Pauri Garhwal', 'Pithoragarh','Rudraprayag','Tehri Garhwal','Udham Singh Nagar','Uttarkashi'],	
    'West Bengal':[ 'Alipurduar', 'Bankura', 'Birbhum','Cooch Behar','Dakshin Dinajpur', 'Darjeeling', 'Hooghly','Howrah','Jalpaiguri', 'Jhargram', 'Kalimpong', 'Kolkata', 'Malda', 'Murshidabad', 'Nadia', 'North 24 Parganas','Paschim Bardhaman','Paschim Medinipur','Purba Bardhaman','Purba Medinipur', 'Purulia',  'South 24 Parganas','Uttar Dinajpur'],
}

USER_TYPES = [
    'Taxpayer',
    'Tax Deductor',
    'Tax Collector (e-Commerce)',
    'GST Practitioner',
    'Non Resident Texable Person',
    'United Nation Body',
    'Consulate or Embassy of Foreign Country',
    'Other Notified Person',
    'Non-Resident Online Services Provider',
]

# Test credentials for validation
ALLOWED_TEST_CREDENTIALS = [
    {
        'user_type': 'Taxpayer',
        'state': 'Maharashtra',
        'district': 'Mumbai City',
        'business_name': 'Jagadish Traders',
        'pan_number': 'VJYCJ0054M',
        'email': 'jagadishl1974@icommail.com',
        'mobile': '2206197454'
    },
    {
        'user_type': 'Taxpayer',
        'state': 'Maharashtra',
        'district': 'Thane',
        'business_name': 'Vishwa Bhai Agencies',
        'pan_number': 'VISCV0055M',
        'email': 'vishwaramadorai@icommail.com',
        'mobile': '2901199955'
    },
    {
        'user_type': 'Taxpayer',
        'state': 'Tamil Nadu',
        'district': 'Chennai',
        'business_name': 'Vijay Associates',
        'pan_number': 'VJYAV0027M',
        'email': 'vijayvishwa@icommail.com',
        'mobile': '2000102627'
    },
    {
        'user_type': 'Taxpayer',
        'state': 'Tamil Nadu',
        'district': 'Coimbatore',
        'business_name': 'Saravana Agencies',
        'pan_number': 'VELAV0038M',
        'email': 'saravana@icommail.com',
        'mobile': '2004170438'
    },
    {
        'user_type': 'Taxpayer',
        'state': 'Karnataka',
        'district': 'Bengaluru Urban',
        'business_name': 'Das Electricals',
        'pan_number': 'LDSTL0067M',
        'email': 'leodas@icommail.com',
        'mobile': '2023191067'
    }
]


def validate_test_credentials(form_data):
    """
    Validate form data against allowed test credentials
    Returns (is_valid, error_message)
    """
    if not form_data:
        return False, "No form data received"

    for i, allowed_credential in enumerate(ALLOWED_TEST_CREDENTIALS):
        user_type_match = form_data.get('user_type') == allowed_credential.get('user_type')
        state_match = form_data.get('state') == allowed_credential.get('state')
        district_match = form_data.get('district') == allowed_credential.get('district')
        business_name_match = form_data.get('business_name') == allowed_credential.get('business_name')
        pan_match = form_data.get('pan_number') == allowed_credential.get('pan_number')
        email_match = form_data.get('email') == allowed_credential.get('email')
        mobile_match = form_data.get('mobile') == allowed_credential.get('mobile')

        if (user_type_match and state_match and district_match and
            business_name_match and pan_match and email_match and mobile_match):
            return True, ""

    error_message = "Registration Error: Only test credentials are allowed. Please use one of the following valid combinations:"
    for i, credential in enumerate(ALLOWED_TEST_CREDENTIALS):
        error_message += f"\n\n{i+1}. User Type: {credential.get('user_type', 'N/A')}"
        error_message += f"\n   State: {credential.get('state', 'N/A')}"
        error_message += f"\n   District: {credential.get('district', 'N/A')}"
        error_message += f"\n   Business Name: {credential.get('business_name', 'N/A')}"
        error_message += f"\n   PAN: {credential.get('pan_number', 'N/A')}"
        error_message += f"\n   Email: {credential.get('email', 'N/A')}"
        error_message += f"\n   Mobile: {credential.get('mobile', 'N/A')}"

    return False, error_message

def registration_step1(request):
    """Handle the first step of registration"""
    if request.method == 'POST':
        form_data = {
            'user_type': request.POST.get('user_type'),
            'state': request.POST.get('state'),
            'district': request.POST.get('district'),
            'business_name': request.POST.get('business_name'),
            'pan_number': request.POST.get('pan_number'),
            'email': request.POST.get('email'),
            'mobile': request.POST.get('mobile'),
        }

        is_valid, error_message = validate_test_credentials(form_data)

        if not is_valid:
            messages.error(request, error_message)
            context = {
                'states_districts': STATES_DISTRICTS,
                'user_types': USER_TYPES,
                'form_data': form_data,
            }
            return render(request, 'step1.html', context)

        request.session['registration_data'] = form_data
        request.session['mobile_otp'] = '123456'
        request.session['email_otp'] = '123456'
        return redirect('registration_step2')

    context = {
        'states_districts': STATES_DISTRICTS,
        'user_types': USER_TYPES,
    }
    return render(request, 'step1.html', context)

def registration_step2(request):
    """OTP verification step (supports single 'otp' OR both 'mobile_otp' + 'email_otp')."""
    if 'registration_data' not in request.session:
        messages.error(request, 'Session expired. Please start registration again.')
        return redirect('registration_step1')

    if request.method == 'POST':
        single_otp = (request.POST.get('otp') or '').strip()
        mobile_otp = (request.POST.get('mobile_otp') or '').strip()
        email_otp  = (request.POST.get('email_otp') or '').strip()

        sess_mobile = (request.session.get('mobile_otp') or '').strip()
        sess_email  = (request.session.get('email_otp') or '').strip()

        # CASE A: one input named 'otp' (match either mobile or email session OTP)
        if single_otp:
            reg_ok = (single_otp == sess_mobile) or (single_otp == sess_email)
        else:
            # CASE B: two inputs named 'mobile_otp' and 'email_otp' (require both)
            reg_ok = (mobile_otp and email_otp and (mobile_otp == sess_mobile) and (email_otp == sess_email))

        if reg_ok:
            registration_data = request.session.get('registration_data', {})
            biz_name = registration_data.get('business_name') or 'User'
            messages.success(request, f'Registration successful! Welcome, {biz_name}')

            for key in ('registration_data', 'mobile_otp', 'email_otp'):
                request.session.pop(key, None)

            return redirect('registration_success')
        else:
            messages.error(request, 'Invalid OTP. Please try again.')

    return render(request, 'step2.html')

@csrf_exempt
def get_districts(request):
    """AJAX endpoint to get districts based on selected state"""
    if request.method == 'POST':
        data = json.loads(request.body)
        state = data.get('state')
        districts = STATES_DISTRICTS.get(state, [])
        return JsonResponse({'districts': districts})
    return JsonResponse({'districts': []})

@csrf_exempt
def resend_otp(request):
    """AJAX endpoint to resend OTP"""
    if request.method == 'POST':
        data = json.loads(request.body)
        otp_type = data.get('type')  # 'mobile' or 'email'

        new_otp = '123456'

        if otp_type == 'mobile':
            request.session['mobile_otp'] = new_otp
            return JsonResponse({'success': True, 'message': 'Mobile OTP resent successfully', 'otp': new_otp})
        elif otp_type == 'email':
            request.session['email_otp'] = new_otp
            return JsonResponse({'success': True, 'message': 'Email OTP resent successfully', 'otp': new_otp})

    return JsonResponse({'success': False, 'message': 'Failed to resend OTP'})

def registration_success(request):
    """Registration success page"""
    return render(request, 'registrationsuccesful.html')

# -------------------- TRN / OTP / Dashboards --------------------

VALID_TRNS = ["172200059541TRN"]
CAPTCHA_CODE = "519741"

def trn_page(request):
    if request.method == "POST":
        trn = (request.POST.get("trn") or "").strip()
        captcha = (request.POST.get("captcha") or "").strip().lower()
        if trn in VALID_TRNS:
            if captcha == CAPTCHA_CODE.lower():
                request.session['trn'] = trn
                return redirect('verify_otp')
            messages.error(request, "Invalid CAPTCHA. Please try again.")
        else:
            messages.error(request, "Invalid TRN. Please enter a valid Temporary Reference Number.")
    return render(request, 'trn_login.html')

def verify_otp(request):
    if request.method == 'POST':
        otp_entered = request.POST.get('otp')
        if otp_entered == '123456':
            messages.success(request, 'OTP verified successfully!')
            return redirect('gst_ledger_dashboard')
        messages.error(request, 'Invalid OTP. Please try again.')
    return render(request, 'verify_otp.html')

def otp_success(request):
    return render(request, 'otp_success.html')

def NIL_Return_Filinglog(request):
    if request.method == 'POST':
        username = (request.POST.get('username') or '').strip()
        password = (request.POST.get('password') or '').strip()
        captcha  = (request.POST.get('captcha')  or '').strip()
        if captcha.lower() != '519741':
            messages.error(request, 'Invalid CAPTCHA. Please try again.')
            return render(request, 'NIL_Return_Filinglog.html')

        LOGIN_MAP = {
            'NERGYINDIA': ('Nergy@123', 2),
            'ELECTRO': ('Elect@22', 3),
            'RAHUL@45': ('Rk@123', 4),
        }
        entry = LOGIN_MAP.get(username.upper())
        if entry:
            expected_pwd, content_id = entry
            if password == expected_pwd and CourseContent1.objects.filter(pk=content_id).exists():
                return redirect('trn_dashboard_with_id', content_id=content_id)

        messages.error(request, 'Invalid login credentials.')
        return render(request, 'NIL_Return_Filinglog.html')

    return render(request, 'NIL_Return_Filinglog.html')

def trn_dashboard(request, content_id=None):
    cid = _resolve_task_id(request, content_id)
    request.session["last_content_id"] = cid
    request.session.modified = True
    company = _trade_name_for_task(cid)  # already UPPERCASE
    return render(request, "trn_dashboard.html", {
        "content_id": cid,
        "company": company,
        "welcome_title": f"Welcome {company} to GST Common Portal",
    })

def gst_ledger_dashboard(request, content_id=None):
    cid = _resolve_task_id(request, content_id)
    request.session["last_content_id"] = cid
    request.session.modified = True

    company = _trade_name_for_task(cid)  # UPPERCASE
    expected = f"/gst_ledger_dashboard/{cid}/"
    if request.path != expected:
        return redirect(expected)

    return render(request, "gst_ledger_dashboard.html", {
        "content_id": cid,
        "company": company,
        "welcome_title": f"Welcome {company} to GST Common Portal",
    })

def file_returns(request, content_id=None):
    cid = _resolve_task_id(request, content_id)
    request.session["last_content_id"] = cid
    request.session.modified = True

    obj = get_object_or_404(CourseContent1, pk=cid)
    meta = parse_task_info_para(obj.task_info or "")

    legal_name = _legal_name_for_task(cid)
    trade_name = _trade_name_for_task(cid)  # UPPERCASE
    company = trade_name

    mon, yr = _return_period_to_month_year(meta.get("ReturnPeriod"), meta.get("FY"))
    gstr1_due_pretty = ""
    gstr3b_due_pretty = ""
    if mon and yr:
        g1d = _compute_due_date_for_gstr1(mon, yr)
        g3d = _compute_due_date_for_gstr3b(mon, yr)
        gstr1_due_pretty = f"Due Date - {_format_date_ind(g1d)}"
        gstr3b_due_pretty = f"Due Date - {_format_date_ind(g3d)}"

    expected = f"/file-returns/{cid}/"
    if request.path != expected:
        return redirect(expected)

    return render(request, "file_returns.html", {
        "content_id": cid,
        "company": company,
        "welcome_title": f"Welcome {company} to GST Common Portal",
        "legal_name": legal_name,
        "gstin": meta.get("GSTIN") or "",
        "trade_name": trade_name,   # UPPERCASE
        "fy": meta.get("FY") or "",
        "return_period": meta.get("ReturnPeriod") or "",
        "gstr1_due": gstr1_due_pretty,
        "gstr3b_due": gstr3b_due_pretty,
    })

@require_GET
def course_content_basic(request, pk: int):
    obj = get_object_or_404(CourseContent1.objects.select_related("topic"), pk=pk)
    company = _trade_name_for_task(obj.pk)  # UPPERCASE
    return JsonResponse({
        "id": obj.pk,
        "company": company,
        "welcome_title": f"Welcome {company} to GST Common Portal",
    })

# -------------------- GSTR-1 page + JSON --------------------

def gstr1_summary(request, content_id=None):
    cid = _resolve_task_id(request, content_id)
    request.session["last_content_id"] = cid
    request.session.modified = True

    obj = get_object_or_404(CourseContent1, pk=cid)
    meta = parse_task_info_para(obj.task_info or "")

    legal_name = _legal_name_for_task(cid)
    trade_name = _trade_name_for_task(cid)  # UPPERCASE
    company = trade_name

    mon, yr = _return_period_to_month_year(meta.get("ReturnPeriod"), meta.get("FY"))
    due_pretty = ""
    if mon and yr:
        due_pretty = _format_date_ind(_compute_due_date_for_gstr1(mon, yr))

    return render(request, 'gstr1_summary.html', {
        "content_id": cid,
        "company": company,
        "welcome_title": f"Welcome {company} to GST Common Portal",
        "gstin": meta.get("GSTIN") or "",
        "trade_name": trade_name,   # UPPERCASE
        "legal_name": legal_name,
        "fy": meta.get("FY") or "",
        "return_period": meta.get("ReturnPeriod") or "",
        "due_date": due_pretty,
    })

def gstr1_task_meta(request, content_id=None):
    cid = _resolve_task_id(request, content_id)
    obj = get_object_or_404(CourseContent1, pk=cid)
    meta = parse_task_info_para(obj.task_info or "")

    mon, yr = _return_period_to_month_year(meta.get("ReturnPeriod"), meta.get("FY"))
    due_iso = ""
    due_pretty = ""
    if mon and yr:
        d = _compute_due_date_for_gstr1(mon, yr)
        due_iso = d.isoformat()
        due_pretty = _format_date_ind(d)

    payload = {
        "id": obj.id,
        "meta": {
            "GSTIN": meta.get("GSTIN") or "",
            "FY": meta.get("FY") or "",
            "ReturnPeriod": meta.get("ReturnPeriod") or "",
            "TradeName": _trade_name_for_task(cid),   # UPPERCASE
            "LegalName": _legal_name_for_task(cid),   # falls back to AKHIL VASUDEV
            "DueDateISO": due_iso,
            "DueDatePretty": due_pretty,
        }
    }
    return JsonResponse(payload)




from django.shortcuts import render, redirect
from django.contrib import messages
from django.urls import reverse

# ==== Hardcoded valid TRNs & mapping to question/content ids ====
VALID_TRNS = [
    "201600059591TRN",
    "181020170061TRN",
    "640000130164TRN",
    "221020140057TRN",
    "081120070046TRN",
]

# Map TRN → Question ID (already in your file)
TRN_TO_QID = {
    "201600059591TRN": 9,   # Case 1: Vijay Kumar
    "181020170061TRN": 10,  # Case 2: Vetrimaaran
    "640000130164TRN": 11,  # Case 3: John Durairaj
    "221020140057TRN": 12,  # Case 4: Jeevanandham
    "081120070046TRN": 13,  # Case 5: Guru Prasad
}

# ---------- CASE MASTER DATA (for auto-prefill on Business page) ----------
CASE_DATA = {
    9: {   # Vijay Kumar – Kumar Enterprise, Noida
        "legal_name": "Kumar Enterprise",
        "pan": "VJYXV0059M",
        "state": "Uttar Pradesh",
        "district": "Gautam Buddha Nagar",
        "reason_default": "Voluntary Basis",
        "commencement_date": "08-12-2021",
    },
    10: {  # Vetrimaaran – Vetri Enterprise, Noida
        "legal_name": "Vetri Enterprise",
        "pan": "VTMXV0061M",
        "state": "Uttar Pradesh",
        "district": "Gautam Buddha Nagar",
        "reason_default": "Voluntary Basis",
        "commencement_date": "11-10-2021",
    },
    11: {  # John Durairaj – Durairaj and Sons, Bengaluru
        "legal_name": "Durairaj and Sons",
        "pan": "VJYXD0064M",
        "state": "Karnataka",
        "district": "Bengaluru",
        "reason_default": "Voluntary Basis",
        "commencement_date": "13-01-2021",
    },
    12: {  # Jeevanandham – Jeeva Enterprise, Chennai
        "legal_name": "Jeeva Enterprise",
        "pan": "VJYXJ0057M",
        "state": "Tamil Nadu",
        "district": "Chennai",
        "reason_default": "Voluntary Basis",
        "commencement_date": "02-08-2021",
    },
    13: {  # Guru Prasad – ATM Enterprises, Howrah
        "legal_name": "ATM Enterprises",
        "pan": "GRUXG0046M",
        "state": "West Bengal",
        "district": "Howrah",
        "reason_default": "Voluntary Basis",
        "commencement_date": "08-11-2022",
    },
}


# Simple demo CAPTCHA + OTP
CAPTCHA_CODE = "519741"
DEMO_OTP = "123456"

def trn_page(request):
    """
    TRN login page: validates TRN + CAPTCHA,
    stores TRN + inferred question_id in session, then goes to verify_otp?qid=<id>.
    Also respects optional ?qid= or ?content_id= coming into this view.
    """
    # Allow optional qid/content_id to flow into hidden field (fallback if needed)
    qid_from_query = request.GET.get("qid") or request.GET.get("content_id")

    if request.method == "POST":
        trn = (request.POST.get("trn") or "").strip()
        captcha = (request.POST.get("captcha") or "").strip().lower()
        qid_hidden = (request.POST.get("qid") or "").strip()  # hidden field

        if trn in VALID_TRNS:
            if captcha == CAPTCHA_CODE.lower():
                # Prefer mapping from TRN → question id
                question_id = TRN_TO_QID.get(trn)
                # If for any reason mapping isn't present, fallback to hidden value
                if not question_id and qid_hidden.isdigit():
                    question_id = int(qid_hidden)

                if not question_id:
                    messages.error(request, "Could not determine the related question. Please try again.")
                    return render(request, "trn_login.html", {"qid": qid_from_query})

                # Persist in session for later steps
                request.session["trn"] = trn
                request.session["question_id"] = question_id

                # Go to OTP with qid as query param (also usable without session)
                otp_url = f"{reverse('verify_otp')}?qid={question_id}"
                return redirect(otp_url)
            else:
                messages.error(request, "Invalid CAPTCHA. Please try again.")
        else:
            messages.error(request, "Invalid TRN. Please enter a valid Temporary Reference Number.")

    return render(request, "trn_login.html", {"qid": qid_from_query})


def verify_otp(request):
    """
    Very simple OTP step:
    - GET: show form
    - POST: check OTP, then redirect to trn_dashboard/<qid> 
    """
    # Prefer query param, fallback to session
    qid_param = request.GET.get("qid") or request.POST.get("qid")
    if not qid_param:
        qid_param = str(request.session.get("question_id") or "")

    if request.method == "POST":
        otp = (request.POST.get("otp") or "").strip()
        if otp == DEMO_OTP and qid_param.isdigit():
            # On success, redirect with the content_id
            return redirect("trn_dashboard_with_id", content_id=int(qid_param))
        else:
            messages.error(request, "Invalid OTP. Please try again.")

    return render(request, "verify_otp.html", {"qid": qid_param, "demo_otp": DEMO_OTP})




def gst_dashboard(request):
    creation_date = datetime.now().date()
    expiry_date = creation_date + timedelta(days=15)
    
    context = {
        'creation_date': creation_date.strftime("%d/%m/%Y"),
        'expiry_date': expiry_date.strftime("%d/%m/%Y"),
    }
    return render(request, 'gst_dashboard.html', context)







from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.urls import reverse

# ===================== TRN CONFIG =====================

VALID_TRNS = [
    "201600059591TRN",
    "181020170061TRN",
    "640000130164TRN",
    "221020140057TRN",
    "081120070046TRN",
]

# Map TRN → Question ID (1..5 or whatever you want)
TRN_TO_QID = {
    "201600059591TRN": 9,   # Vijay Kumar
    "181020170061TRN": 10,
    "640000130164TRN": 11,
    "221020140057TRN": 12,
    "081120070046TRN": 13,
}

CAPTCHA_CODE = "519741"
DEMO_OTP = "123456"

# ===================== WIZARD HELPERS =====================

def _wizard_session_key(qid: int) -> str:
    return f"reg_wizard_{qid}"

def _wizard_get(request, qid: int) -> dict:
    data = request.session.get(_wizard_session_key(qid), {})
    data.setdefault("business", {})
    data.setdefault("proprietor", {})
    data.setdefault("authorized_signatory", {})
    data.setdefault("authorized_rep", {})
    data.setdefault("biz_address", {})
    return data

def _wizard_store(request, qid: int, patch: dict):
    data = _wizard_get(request, qid)
    for key, val in patch.items():
        if isinstance(val, dict):
            data[key].update(val)
        else:
            data[key] = val
    request.session[_wizard_session_key(qid)] = data
    request.session.modified = True

def _nav_urls(qid: int):
    """For now all tabs point to Business step until you create others."""
    business_url = reverse("step_business_details", args=[qid])
    return {
        "business": business_url,
        "promoter": business_url,
        "signatory": business_url,
        "rep": business_url,
        "ppob": business_url,
        "apob": business_url,
        "goods": business_url,
        "state": business_url,
        "aadhaar": business_url,
        "verify": business_url,
    }

# ===================== TRN LOGIN & OTP =====================

def trn_page(request):
    """
    TRN login: checks TRN + CAPTCHA, then sends user to OTP page with qid.
    """
    qid_from_query = request.GET.get("qid") or request.GET.get("content_id")

    if request.method == "POST":
        trn = (request.POST.get("trn") or "").strip()
        captcha = (request.POST.get("captcha") or "").strip().lower()
        qid_hidden = (request.POST.get("qid") or "").strip()

        if trn in VALID_TRNS:
            if captcha == CAPTCHA_CODE.lower():
                question_id = TRN_TO_QID.get(trn)
                if not question_id and qid_hidden.isdigit():
                    question_id = int(qid_hidden)

                if not question_id:
                    messages.error(request, "Could not determine related question for this TRN.")
                    return render(request, "trn_login.html", {"qid": qid_from_query})

                request.session["trn"] = trn
                request.session["question_id"] = question_id

                otp_url = f"{reverse('verify_otp')}?qid={question_id}"
                return redirect(otp_url)
            else:
                messages.error(request, "Invalid CAPTCHA. Please try again.")
        else:
            messages.error(request, "Invalid TRN. Please enter a valid Temporary Reference Number.")

    return render(request, "trn_login.html", {"qid": qid_from_query})


def verify_otp(request):
    """
    OTP page: after success, go directly to Step 1 (Business Details)
    """
    qid_param = request.GET.get("qid") or request.POST.get("qid")
    if not qid_param:
        qid_param = str(request.session.get("question_id") or "")

    if request.method == "POST":
        otp = (request.POST.get("otp") or "").strip()
        if otp == DEMO_OTP and qid_param.isdigit():
            return redirect("step_business_details", qid=int(qid_param))
        else:
            messages.error(request, "Invalid OTP. Please try again.")

    return render(request, "verify_otp.html", {
        "qid": qid_param,
    })

# ===================== STEP 1: BUSINESS DETAILS =====================

def step_business_details(request, qid: int):
    """
    First page after OTP – full Business Details form.
    """
    app = _wizard_get(request, qid)

    if request.method == "POST":
        _wizard_store(request, qid, {
            "business": {
                "legal_name": request.POST.get("legal_name"),
                "trade_name": request.POST.get("trade_name"),
                "pan": request.POST.get("pan"),
                "constitution": request.POST.get("constitution"),
                "reason": request.POST.get("reason"),
                "reg_date": request.POST.get("reg_date"),
            }
        })
        messages.success(request, "Business details saved. You can move to next tab.")
        # For now stay on same page. Later you can redirect to next step.
        return redirect("step_business_details", qid=qid)

    return render(request, "step_business_details.html", {
        "qid": qid,
        "app": app,
        "nav": _nav_urls(qid),
        "active": "business",
    })



def step_promoters(request, qid: int):
    """
    Step 2 – Promoter / Partners.
    For now we store only one promoter (main proprietor) in session.
    """
    app = _wizard_get(request, qid)
    existing = app.get("promoter", {})

    if request.method == "POST":
        promoter_data = {
            "name": request.POST.get("name") or "",
            "father_name": request.POST.get("father_name") or "",
            "dob": request.POST.get("dob") or "",
            "gender": request.POST.get("gender") or "",
            "mobile": request.POST.get("mobile") or "",
            "email": request.POST.get("email") or "",
            "designation": request.POST.get("designation") or "",
            "aadhaar": request.POST.get("aadhaar") or "",
            "pan": request.POST.get("pan") or "",
            "address": request.POST.get("address") or "",
        }

        _wizard_store(request, qid, {"promoter": promoter_data})
        messages.success(request, "Promoter details saved.")
        # later you can redirect to next step:
        # return redirect("step_principal_place", qid=qid)
        return redirect("step_promoters", qid=qid)

    return render(request, "step_promoters.html", {
        "qid": qid,
        "app": app,
        "promoter": existing,
        "nav": _nav_urls(qid),
        "active": "promoters",
    })


# ===================== STEP 3: AUTHORIZED SIGNATORY =====================

def step_authorized_signatory(request, qid: int):
    """
    Step 3 – Authorized Signatory
    Stores: name, mobile, email, designation, relation type
    """
    app = _wizard_get(request, qid)
    existing = app.get("authorized_signatory", {})

    if request.method == "POST":
        sign_data = {
            "name": request.POST.get("name") or "",
            "mobile": request.POST.get("mobile") or "",
            "email": request.POST.get("email") or "",
            "designation": request.POST.get("designation") or "",
            "relation": request.POST.get("relation") or "",
            "aadhaar": request.POST.get("aadhaar") or "",
            "pan": request.POST.get("pan") or "",
            "address": request.POST.get("address") or "",
        }

        _wizard_store(request, qid, {"authorized_signatory": sign_data})
        messages.success(request, "Authorized Signatory details saved.")
        # Later redirect to next step
        return redirect("step_authorized_signatory", qid=qid)

    return render(request, "step_authorized_signatory.html", {
        "qid": qid,
        "app": app,
        "signatory": existing,
        "nav": _nav_urls(qid),
        "active": "signatory",
    })



# ===================== STEP 4: AUTHORIZED REPRESENTATIVE =====================

def step_authorized_representative(request, qid: int):
    """
    Step 4 – Authorized Representative
    Only required if the taxpayer has appointed a GST Authorized Representative.
    """
    app = _wizard_get(request, qid)
    existing = app.get("authorized_representative", {})

    if request.method == "POST":
        # "required" field tells if they have representative or not
        rep_required = request.POST.get("rep_required") or "No"

        rep_data = {
            "rep_required": rep_required,
            "name": request.POST.get("name") or "",
            "enrolment_id": request.POST.get("enrolment_id") or "",
            "pan": request.POST.get("pan") or "",
            "mobile": request.POST.get("mobile") or "",
            "email": request.POST.get("email") or "",
            "address": request.POST.get("address") or "",
        }

        _wizard_store(request, qid, {"authorized_representative": rep_data})
        messages.success(request, "Authorized Representative details saved.")

        # For now, stay on same step. Later you can redirect to next step page.
        return redirect("step_authorized_representative", qid=qid)

    return render(request, "step_authorized_representative.html", {
        "qid": qid,
        "app": app,
        "rep": existing,
        "nav": _nav_urls(qid),
        "active": "authorized_rep",
    })



from django.contrib import messages

# ===================== STEP 5: PRINCIPAL PLACE OF BUSINESS =====================

def step_principal_place(request, qid: int):
    """
    Step 5 – Principal Place of Business
    Captures full address + nature of premises + business activities at this place.
    Data is stored in session via _wizard_store.
    """
    app = _wizard_get(request, qid)
    existing = app.get("principal_place", {})

    # Optionally prefill state/district from basic/business step if you stored them there
    basic = app.get("business", {}) or app.get("basic", {})

    if request.method == "POST":
        activities = request.POST.getlist("business_activities")

        pp_data = {
            "building": request.POST.get("building") or "",
            "floor": request.POST.get("floor") or "",
            "street": request.POST.get("street") or "",
            "locality": request.POST.get("locality") or "",
            "city": request.POST.get("city") or "",
            "pincode": request.POST.get("pincode") or "",
            "state": request.POST.get("state") or "",
            "district": request.POST.get("district") or "",
            "nature_of_premises": request.POST.get("nature_of_premises") or "",
            "contact_mobile": request.POST.get("contact_mobile") or "",
            "contact_email": request.POST.get("contact_email") or "",
            "business_activities": activities,
            "has_additional_places": request.POST.get("has_additional_places") or "No",
        }

        _wizard_store(request, qid, {"principal_place": pp_data})
        messages.success(request, "Principal Place of Business details saved.")
        # For now stay on the same page. Later you can redirect to Step 6.
        return redirect("step_principal_place", qid=qid)

    return render(request, "step_principal_place.html", {
        "qid": qid,
        "app": app,
        "pp": existing,
        "basic": basic,
        "nav": _nav_urls(qid),
        "active": "principal_place",
    })



from django.contrib import messages

# ===================== STEP 6: ADDITIONAL PLACES OF BUSINESS =====================

def step_additional_places(request, qid: int):
    """
    Step 6 – Additional Places of Business
    - Shows list of already added additional places (from session)
    - Lets user add one new additional place at a time
    - Lets user delete an existing additional place
    """
    app = _wizard_get(request, qid)
    places = app.get("additional_places") or []
    principal = app.get("principal_place", {})

    if request.method == "POST":
        action = request.POST.get("action", "add")

        # ---------- DELETE ----------
        if action == "delete":
            index_str = request.POST.get("index")
            try:
                idx = int(index_str)
            except (TypeError, ValueError):
                messages.error(request, "Invalid item selected for deletion.")
                return redirect("step_additional_places", qid=qid)

            if 0 <= idx < len(places):
                deleted = places.pop(idx)
                _wizard_store(request, qid, {"additional_places": places})
                messages.success(
                    request,
                    f"Additional place at {deleted.get('city', 'selected row')} deleted."
                )
            else:
                messages.error(request, "Invalid index for deletion.")
            return redirect("step_additional_places", qid=qid)

        # ---------- ADD ----------
        activities = request.POST.getlist("business_activities")

        new_place = {
            "building": request.POST.get("building") or "",
            "floor": request.POST.get("floor") or "",
            "street": request.POST.get("street") or "",
            "locality": request.POST.get("locality") or "",
            "city": request.POST.get("city") or "",
            "pincode": request.POST.get("pincode") or "",
            "state": request.POST.get("state") or "",
            "district": request.POST.get("district") or "",
            "nature_of_premises": request.POST.get("nature_of_premises") or "",
            "business_activities": activities,
            "contact_mobile": request.POST.get("contact_mobile") or "",
            "contact_email": request.POST.get("contact_email") or "",
        }

        # Basic validation: require at least city & pincode to add
        if not new_place["city"] or not new_place["pincode"]:
            messages.error(request, "Please fill at least City/Town and PIN Code to add an additional place.")
        else:
            places.append(new_place)
            _wizard_store(request, qid, {"additional_places": places})
            messages.success(request, "Additional place of business added successfully.")
            return redirect("step_additional_places", qid=qid)

    return render(request, "step_additional_places.html", {
        "qid": qid,
        "app": app,
        "places": places,
        "principal": principal,
        "nav": _nav_urls(qid),
        "active": "additional_places",
    })

from django.contrib import messages

# ===================== STEP 7: GOODS & SERVICES =====================

def step_goods_services(request, qid: int):
    """
    Step 7 – Goods & Services
    - Shows list of goods/services (HSN/SAC) already added
    - Lets user add a new row
    - Lets user delete an existing row
    All stored in session under key 'goods_services'.
    """
    app = _wizard_get(request, qid)
    items = app.get("goods_services") or []

    if request.method == "POST":
        action = request.POST.get("action", "add")

        # ---------- DELETE ----------
        if action == "delete":
            index_str = request.POST.get("index")
            try:
                idx = int(index_str)
            except (TypeError, ValueError):
                messages.error(request, "Invalid item selected for deletion.")
                return redirect("step_goods_services", qid=qid)

            if 0 <= idx < len(items):
                deleted = items.pop(idx)
                _wizard_store(request, qid, {"goods_services": items})
                messages.success(
                    request,
                    f"Item '{deleted.get('description', 'selected row')}' removed."
                )
            else:
                messages.error(request, "Invalid index for deletion.")
            return redirect("step_goods_services", qid=qid)

        # ---------- ADD ----------
        supply_type = request.POST.get("supply_type") or "Goods"
        description = (request.POST.get("description") or "").strip()
        hsn_sac     = (request.POST.get("hsn_sac") or "").strip()
        is_exempt   = bool(request.POST.get("is_exempt"))
        is_nill     = bool(request.POST.get("is_nill"))
        is_non_gst  = bool(request.POST.get("is_non_gst"))

        if not description or not hsn_sac:
            messages.error(request, "Description and HSN/SAC Code are mandatory.")
        else:
            new_item = {
                "supply_type": supply_type,
                "description": description,
                "hsn_sac": hsn_sac,
                "is_exempt": is_exempt,
                "is_nill": is_nill,
                "is_non_gst": is_non_gst,
            }
            items.append(new_item)
            _wizard_store(request, qid, {"goods_services": items})
            messages.success(request, "Goods/Services item added successfully.")
            return redirect("step_goods_services", qid=qid)

    return render(request, "step_goods_services.html", {
        "qid": qid,
        "app": app,
        "items": items,
        "nav": _nav_urls(qid),
        "active": "goods_services",
    })



def step_state_specific(request, qid: int):
    """
    Step 8 – State Specific Information
    Saved in: session["registration"][qid]["state_specific"]
    """

    # Load full session dictionary
    reg = request.session.get("registration", {})

    # Load application for this qid
    app = reg.get(str(qid), {})

    if request.method == "POST":

        app["state_specific"] = {
            "state": request.POST.get("state") or "",
            "pt_enrolment": request.POST.get("pt_enrolment") or "",
            "pt_number": request.POST.get("pt_number") or "",
            "local_reg_no": request.POST.get("local_reg_no") or "",
        }

        # Save back to session
        reg[str(qid)] = app
        request.session["registration"] = reg
        request.session.modified = True

        messages.success(request, "State Specific Information saved successfully.")
        return redirect("step_state_specific", qid=qid)

    return render(request, "step_state_specific.html", {
        "qid": qid,
        "saved": app.get("state_specific", {}),
        "active": "state",       # activates sidebar highlight
    })


def step_aadhaar(request, qid: int):
    """
    Step 9 – Aadhaar Authentication
    Saved in: session["registration"][qid]["aadhaar"]
    """
    reg = request.session.get("registration", {})
    app = reg.get(str(qid), {})

    saved_aadhaar = app.get("aadhaar", {})

    if request.method == "POST":
        aadhaar_no = (request.POST.get("aadhaar_no") or "").strip()
        consent = request.POST.get("consent") == "on"
        otp = (request.POST.get("otp") or "").strip()

        errors = []

        # Basic checks
        if not aadhaar_no:
            errors.append("Please enter Aadhaar number.")
        elif not aadhaar_no.isdigit() or len(aadhaar_no) != 12:
            errors.append("Aadhaar number must be 12 digits.")

        if not consent:
            errors.append("You must give consent for Aadhaar authentication.")

        if not otp:
            errors.append("Please enter OTP sent to Aadhaar-linked mobile.")
        elif otp != DEMO_OTP:
            errors.append("Invalid OTP. Use demo OTP 123456 for practice.")

        if errors:
            for e in errors:
                messages.error(request, e)
        else:
            # All good - mark Aadhaar as verified
            app["aadhaar"] = {
                "aadhaar_no": aadhaar_no,
                "consent": True,
                "otp_verified": True,
            }
            reg[str(qid)] = app
            request.session["registration"] = reg
            request.session.modified = True

            messages.success(request, "Aadhaar authentication completed successfully.")

            # Go to final Verification step (step 10)
            return redirect("step_verification", qid=qid)

        saved_aadhaar = {
            "aadhaar_no": aadhaar_no,
            "consent": consent,
            "otp_verified": False,
        }

    return render(request, "step_aadhaar.html", {
        "qid": qid,
        "saved": saved_aadhaar,
        "active": "aadhaar",   # for sidebar highlight
        "demo_otp": DEMO_OTP,  # you can show it in UI for practice
    })




from django.utils import timezone

def step_verification(request, qid: int):
    """
    Step 10 – Verification
    Stores final declaration in:
        session["registration"][qid]["verification"]
    """
    reg = request.session.get("registration", {})
    app = reg.get(str(qid), {})          # all previous step data for this qid
    saved_ver = app.get("verification", {})

    today = timezone.now().date()

    if request.method == "POST":
        declaration = request.POST.get("declaration") == "on"
        place = (request.POST.get("place") or "").strip()
        date_str = request.POST.get("date") or ""

        errors = []

        if not declaration:
            errors.append("You must tick the declaration checkbox before submission.")

        if not place:
            errors.append("Please enter the place (city/town).")

        if not date_str:
            # if user leaves blank, we treat as today’s date
            date_str = today.strftime("%Y-%m-%d")

        if errors:
            for e in errors:
                messages.error(request, e)
        else:
            # Save verification info in session
            app["verification"] = {
                "declared": True,
                "place": place,
                "date": date_str,
            }
            reg[str(qid)] = app
            request.session["registration"] = reg
            request.session.modified = True

            messages.success(
                request,
                "Application verified and submitted successfully (practice mode)."
            )

            # You can redirect to a final success page if you like:
            # return redirect("gst_dashboard")
            # For now, reload same page so student sees success state.
            saved_ver = app["verification"]

    return render(request, "step_verification.html", {
        "qid": qid,
        "app": app,                 # ALL data from previous steps
        "saved_ver": saved_ver,     # Only verification block
        "today": today,
        "active": "verification",   # for sidebar highlight
    })
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.urls import reverse
from django.utils import timezone
from datetime import date, timedelta

# ===================== TRN CONFIG =====================

VALID_TRNS = [
    "201600059591TRN",
    "181020170061TRN",
    "640000130164TRN",
    "221020140057TRN",
    "081120070046TRN",
]

# Map TRN → Question ID (1..5 or whatever you want)
TRN_TO_QID = {
    "201600059591TRN": 9,   # Vijay Kumar
    "181020170061TRN": 10,
    "640000130164TRN": 11,
    "221020140057TRN": 12,
    "081120070046TRN": 13,
}

CAPTCHA_CODE = "519741"
DEMO_OTP = "123456"

# ===================== WIZARD HELPERS =====================

def _wizard_session_key(qid: int) -> str:
    return f"reg_wizard_{qid}"

def _wizard_get(request, qid: int) -> dict:
    """
    Returns the wizard data dict for this qid, always with default
    sub-dicts present.
    """
    data = request.session.get(_wizard_session_key(qid), {})
    data.setdefault("business", {})
    data.setdefault("promoter", {})
    data.setdefault("authorized_signatory", {})
    data.setdefault("authorized_representative", {})
    data.setdefault("principal_place", {})
    data.setdefault("additional_places", [])
    data.setdefault("goods_services", [])
    data.setdefault("state_specific", {})
    data.setdefault("aadhaar", {})
    data.setdefault("verification", {})
    request.session[_wizard_session_key(qid)] = data
    request.session.modified = True
    return data

def _wizard_store(request, qid: int, patch: dict):
    """
    Merge patch into wizard data for this qid (dicts are updated, simple
    values are overwritten).
    """
    data = _wizard_get(request, qid)
    for key, val in patch.items():
        if isinstance(val, dict):
            # ensure sub-dict exists
            if key not in data or not isinstance(data[key], dict):
                data[key] = {}
            data[key].update(val)
        else:
            data[key] = val
    request.session[_wizard_session_key(qid)] = data
    request.session.modified = True

def _nav_urls(qid: int):
    """
    All step URLs used by the 10 tiles.
    """
    return {
        "business": reverse("step_business_details", args=[qid]),
        "promoter": reverse("step_promoters", args=[qid]),
        "signatory": reverse("step_authorized_signatory", args=[qid]),
        "rep": reverse("step_authorized_representative", args=[qid]),
        "ppob": reverse("step_principal_place", args=[qid]),
        "apob": reverse("step_additional_places", args=[qid]),
        "goods": reverse("step_goods_services", args=[qid]),
        "state": reverse("step_state_specific", args=[qid]),
        "aadhaar": reverse("step_aadhaar", args=[qid]),
        "verify": reverse("step_verification", args=[qid]),
    }

def _header_context(request, qid: int, active_step: str) -> dict:
    """
    Builds the context for the top progress bar.
    - Checks 'is_completed' flag to color icons Blue.
    - Sets 'active' class for the current step.
    """
    app = _wizard_get(request, qid)
    
    # The strict order of your pages
    step_order = ["business", "promoter", "signatory", "rep", "ppob", "apob", "goods", "state", "aadhaar", "verify"]
    
    completed_flags = {}

    # Check if each step has been marked as completed in the session
    completed_flags["business"] = app.get("business", {}).get("is_completed", False)
    completed_flags["promoter"] = app.get("promoter", {}).get("is_completed", False)
    completed_flags["signatory"] = app.get("authorized_signatory", {}).get("is_completed", False)
    completed_flags["rep"] = app.get("authorized_representative", {}).get("is_completed", False)
    completed_flags["ppob"] = app.get("principal_place", {}).get("is_completed", False)
    # For list pages, we check if they are marked complete OR if there is data
    completed_flags["apob"] = bool(app.get("additional_places")) or app.get("apob_completed", False)
    completed_flags["goods"] = bool(app.get("goods_services")) or app.get("goods_completed", False)
    completed_flags["state"] = app.get("state_specific", {}).get("is_completed", False)
    completed_flags["aadhaar"] = app.get("aadhaar", {}).get("is_completed", False)
    completed_flags["verify"] = app.get("verification", {}).get("is_completed", False)

    # Calculate Percentage (10% per step)
    completed_count = sum(1 for v in completed_flags.values() if v)
    profile_percent = completed_count * 10
    if profile_percent > 100: profile_percent = 100

    # Assign CSS classes: 'active', 'completed', or 'pending'
    step_status = {}
    for key in step_order:
        if key == active_step:
            step_status[key] = "active"       # Blue Outline
        elif completed_flags.get(key):
            step_status[key] = "completed"    # Solid Blue
        else:
            step_status[key] = "pending"      # Grey

    today_date = date.today()
    return {
        "application_type": "New Registration",
        "due_date": (today_date + timedelta(days=15)).strftime("%d/%m/%Y"),
        "last_modified": today_date.strftime("%d/%m/%Y"),
        "profile_percent": profile_percent,
        "step_status": step_status,
        "nav": _nav_urls(qid),
    }
# ===================== TRN LOGIN & OTP =====================

def trn_page(request):
    """
    TRN login: checks TRN + CAPTCHA, then sends user to OTP page with qid.
    """
    qid_from_query = request.GET.get("qid") or request.GET.get("content_id")

    if request.method == "POST":
        trn = (request.POST.get("trn") or "").strip()
        captcha = (request.POST.get("captcha") or "").strip().lower()
        qid_hidden = (request.POST.get("qid") or "").strip()

        if trn in VALID_TRNS:
            if captcha == CAPTCHA_CODE.lower():
                question_id = TRN_TO_QID.get(trn)
                if not question_id and qid_hidden.isdigit():
                    question_id = int(qid_hidden)

                if not question_id:
                    messages.error(request, "Could not determine related question for this TRN.")
                    return render(request, "trn_login.html", {"qid": qid_from_query})

                request.session["trn"] = trn
                request.session["question_id"] = question_id

                otp_url = f"{reverse('verify_otp')}?qid={question_id}"
                return redirect(otp_url)
            else:
                messages.error(request, "Invalid CAPTCHA. Please try again.")
        else:
            messages.error(request, "Invalid TRN. Please enter a valid Temporary Reference Number.")

    return render(request, "trn_login.html", {"qid": qid_from_query})


def verify_otp(request):
    """
    OTP page: after success, go directly to Step 1 (Business Details)
    """
    qid_param = request.GET.get("qid") or request.POST.get("qid")
    if not qid_param:
        qid_param = str(request.session.get("question_id") or "")

    if request.method == "POST":
        otp = (request.POST.get("otp") or "").strip()
        if otp == DEMO_OTP and qid_param.isdigit():
            return redirect("step_business_details", qid=int(qid_param))
        else:
            messages.error(request, "Invalid OTP. Please try again.")

    return render(request, "verify_otp.html", {
        "qid": qid_param,
    })

# ===================== STEP 1: BUSINESS DETAILS =====================

# ===================== STEP 1: BUSINESS DETAILS =====================

from datetime import date
from django.contrib import messages
from django.shortcuts import render, redirect

# assumes you already have:
# CASE_DATA, _wizard_get, _wizard_store, _header_context

# 1. BUSINESS DETAILS
def step_business_details(request, qid: int):
    app = _wizard_get(request, qid)
    case_info = CASE_DATA.get(qid, {})

    if request.method == "POST":
        biz_block = {
            "legal_name": case_info.get("legal_name", ""),
            "pan": case_info.get("pan", ""),
            "state": case_info.get("state", ""),
            "district": case_info.get("district", ""),
            "trade_name": request.POST.get("trade_name") or "",
            "constitution": request.POST.get("constitution") or "",
            "casual_taxable": "Yes" if request.POST.get("casual_taxable") == "on" else "No",
            "composition_opt": "Yes" if request.POST.get("composition_opt") == "on" else "No",
            "reason": request.POST.get("reason") or "",
            "comm_date": request.POST.get("comm_date") or "",
            "liability_date": request.POST.get("liability_date") or "",
            "existing_reg_type": request.POST.get("existing_reg_type") or "",
            "existing_reg_no": request.POST.get("existing_reg_no") or "",
            "existing_reg_date": request.POST.get("existing_reg_date") or "",
            "is_completed": True # <--- MARKS ICON BLUE
        }
        _wizard_store(request, qid, { "business": biz_block })
        messages.success(request, "Business details saved.")
        # NEXT PAGE:
        return redirect("step_promoters", qid=qid)

    saved_biz = app.get("business", {})
    business_view = {
        "legal_name": case_info.get("legal_name", saved_biz.get("legal_name", "")),
        "pan": case_info.get("pan", saved_biz.get("pan", "")),
        "state": case_info.get("state", saved_biz.get("state", "")),
        "district": case_info.get("district", saved_biz.get("district", "")),
        "trade_name": saved_biz.get("trade_name", ""),
        "constitution": saved_biz.get("constitution", ""),
        "casual_taxable": saved_biz.get("casual_taxable", "No"),
        "composition_opt": saved_biz.get("composition_opt", "No"),
        "reason": saved_biz.get("reason", "") or case_info.get("reason_default", ""),
        "comm_date": saved_biz.get("comm_date", "") or case_info.get("commencement_date", ""),
        "liability_date": saved_biz.get("liability_date", ""),
        "existing_reg_type": saved_biz.get("existing_reg_type", ""),
        "existing_reg_no": saved_biz.get("existing_reg_no", ""),
        "existing_reg_date": saved_biz.get("existing_reg_date", ""),
    }
    return render(request, "step_business_details.html", {
        "qid": qid, "app": app, "business": business_view, **_header_context(request, qid, "business")
    })

# 2. PROMOTERS
def step_promoters(request, qid: int):
    app = _wizard_get(request, qid)
    if request.method == "POST":
        data = request.POST.dict()
        data['is_completed'] = True
        _wizard_store(request, qid, { "promoter": data })
        messages.success(request, "Promoter details saved.")
        # NEXT PAGE:
        return redirect("step_authorized_signatory", qid=qid)
    return render(request, "step_promoters.html", { "qid": qid, "promoter": app.get("promoter", {}), **_header_context(request, qid, "promoter") })

# 3. AUTHORIZED SIGNATORY
def step_authorized_signatory(request, qid: int):
    app = _wizard_get(request, qid)
    if request.method == "POST":
        data = request.POST.dict()
        data['is_completed'] = True
        _wizard_store(request, qid, { "authorized_signatory": data })
        messages.success(request, "Authorized Signatory details saved.")
        # NEXT PAGE:
        return redirect("step_authorized_representative", qid=qid)
    return render(request, "step_authorized_signatory.html", { "qid": qid, "signatory": app.get("authorized_signatory", {}), **_header_context(request, qid, "signatory") })

# 4. AUTHORIZED REPRESENTATIVE
def step_authorized_representative(request, qid: int):
    app = _wizard_get(request, qid)
    if request.method == "POST":
        data = request.POST.dict()
        data['is_completed'] = True
        _wizard_store(request, qid, { "authorized_representative": data })
        messages.success(request, "Authorized Representative details saved.")
        # NEXT PAGE:
        return redirect("step_principal_place", qid=qid)
    return render(request, "step_authorized_representative.html", { "qid": qid, "rep": app.get("authorized_representative", {}), **_header_context(request, qid, "rep") })

# 5. PRINCIPAL PLACE
def step_principal_place(request, qid: int):
    app = _wizard_get(request, qid)
    if request.method == "POST":
        data = request.POST.dict()
        data['business_activities'] = request.POST.getlist("business_activities")
        data['is_completed'] = True
        _wizard_store(request, qid, { "principal_place": data })
        messages.success(request, "Principal Place details saved.")
        # NEXT PAGE:
        return redirect("step_additional_places", qid=qid)
    return render(request, "step_principal_place.html", { "qid": qid, "pp": app.get("principal_place", {}), "basic": app.get("business", {}), **_header_context(request, qid, "ppob") })

# 6. ADDITIONAL PLACES (Special handling for List)
def step_additional_places(request, qid: int):
    app = _wizard_get(request, qid)
    places = app.get("additional_places") or []
    if request.method == "POST":
        action = request.POST.get("action")
        
        if action == "delete":
            try:
                places.pop(int(request.POST.get("index")))
                _wizard_store(request, qid, { "additional_places": places })
                messages.success(request, "Deleted successfully.")
            except (ValueError, IndexError): pass
            return redirect("step_additional_places", qid=qid)
            
        elif action == "save_continue":
            # Mark this step as explicitly completed for color change
            _wizard_store(request, qid, { "apob_completed": True })
            # NEXT PAGE:
            return redirect("step_goods_services", qid=qid)
            
        else: # Add Action
            data = request.POST.dict()
            data['business_activities'] = request.POST.getlist("business_activities")
            if data.get("city") and data.get("pincode"):
                places.append(data)
                _wizard_store(request, qid, { "additional_places": places })
                messages.success(request, "Added successfully.")
            else:
                # If they clicked Save/Continue but without specific action value
                _wizard_store(request, qid, { "apob_completed": True })
                return redirect("step_goods_services", qid=qid)
            return redirect("step_additional_places", qid=qid)
            
    return render(request, "step_additional_places.html", { "qid": qid, "places": places, "principal": app.get("principal_place", {}), **_header_context(request, qid, "apob") })

# 7. GOODS & SERVICES (Special handling for List)
def step_goods_services(request, qid: int):
    app = _wizard_get(request, qid)
    items = app.get("goods_services") or []
    if request.method == "POST":
        action = request.POST.get("action")
        
        if action == "delete":
            try:
                items.pop(int(request.POST.get("index")))
                _wizard_store(request, qid, { "goods_services": items })
                messages.success(request, "Deleted successfully.")
            except (ValueError, IndexError): pass
            return redirect("step_goods_services", qid=qid)
            
        elif action == "save_continue":
             # Mark this step as explicitly completed for color change
             _wizard_store(request, qid, { "goods_completed": True })
             # NEXT PAGE:
             return redirect("step_state_specific", qid=qid)
             
        else: # Add Action
            data = request.POST.dict()
            if data.get("description") and data.get("hsn_sac"):
                data['is_exempt'] = bool(request.POST.get("is_exempt"))
                data['is_nill'] = bool(request.POST.get("is_nill"))
                data['is_non_gst'] = bool(request.POST.get("is_non_gst"))
                items.append(data)
                _wizard_store(request, qid, { "goods_services": items })
                messages.success(request, "Added successfully.")
            else:
                 _wizard_store(request, qid, { "goods_completed": True })
                 return redirect("step_state_specific", qid=qid)
            return redirect("step_goods_services", qid=qid)
            
    return render(request, "step_goods_services.html", { "qid": qid, "items": items, **_header_context(request, qid, "goods") })

# 8. STATE SPECIFIC
def step_state_specific(request, qid: int):
    app = _wizard_get(request, qid)
    if request.method == "POST":
        data = request.POST.dict()
        data['is_completed'] = True
        _wizard_store(request, qid, { "state_specific": data })
        messages.success(request, "State Info saved.")
        # NEXT PAGE:
        return redirect("step_aadhaar", qid=qid)
    return render(request, "step_state_specific.html", { "qid": qid, "saved": app.get("state_specific", {}), **_header_context(request, qid, "state") })

# 9. AADHAAR
def step_aadhaar(request, qid: int):
    app = _wizard_get(request, qid)
    if request.method == "POST":
        if request.POST.get("otp") == DEMO_OTP:
            _wizard_store(request, qid, { "aadhaar": { "aadhaar_no": request.POST.get("aadhaar_no"), "otp_verified": True, "is_completed": True } })
            messages.success(request, "Aadhaar verified.")
            # NEXT PAGE:
            return redirect("step_verification", qid=qid)
        messages.error(request, "Invalid OTP")
    return render(request, "step_aadhaar.html", { "qid": qid, "saved": app.get("aadhaar", {}), "demo_otp": DEMO_OTP, **_header_context(request, qid, "aadhaar") })

# 10. VERIFICATION
def step_verification(request, qid: int):
    app = _wizard_get(request, qid)
    if request.method == "POST":
        if request.POST.get("declaration") == "on":
            _wizard_store(request, qid, { "verification": { "declared": True, "place": request.POST.get("place"), "date": request.POST.get("date") or str(date.today()), "is_completed": True } })
            messages.success(request, "Application Submitted.")
            # FINISH:
            return redirect("gst_dashboard_with_id", qid=qid) 
        else:
            messages.error(request, "Please check declaration.")
        return redirect("step_verification", qid=qid)
    return render(request, "step_verification.html", { "qid": qid, "saved_ver": app.get("verification", {}), "today": date.today(), **_header_context(request, qid, "verify") })