# -*- coding: utf-8 -*-
import os, os.path, sqlite3, shutil
from django.shortcuts import render, render_to_response
from django.views.generic import CreateView, ListView
from django.urls import reverse_lazy
from django.conf import settings
from django.core.files.storage import FileSystemStorage
from submit.models import Submission
from django.http import HttpResponse, HttpResponseRedirect, Http404
from django.contrib.auth.decorators import login_required
from django.contrib.auth import authenticate, login
from django.contrib.auth.forms import UserCreationForm
from django.shortcuts import render, redirect
from django import forms
from acpypeserver import settings as acpypesetting
from submit.models import Submission
from .tasks import process
from .forms import SignUpForm, SubmissionForm
from django.utils import timezone
from acpypeserver.celery import app
from django.contrib.auth.decorators import user_passes_test
from celery import uuid
from django.http import Http404
from django.http import HttpResponse
from django.shortcuts import render, redirect
from django.contrib.auth import login, authenticate
from .forms import SignUpForm
from django.contrib.sites.shortcuts import get_current_site
from django.utils.encoding import force_bytes, force_text
from django.utils.http import urlsafe_base64_encode, urlsafe_base64_decode
from django.template.loader import render_to_string
from .tokens import account_activation_token
from submit.models import Submission, MyUser
from django.core.mail import EmailMessage

DATABASE_HOST = acpypesetting.DATABASES['default']['HOST']
DATABASE_USER = acpypesetting.DATABASES['default']['USER']
DATABASE_PASSWORD = acpypesetting.DATABASES['default']['PASSWORD']
DATABASE_NAME = acpypesetting.DATABASES['default']['NAME']


def home(request):
        return render(request, 'index.html')


class AuthRequiredMiddleware(object):

    def process_request(self, request):
        if not request.user.is_authenticated:
            return HttpResponseRedirect(reverse('/login/'))
            return None

@login_required
def Run(request):
    user_name = request.user.username
    if request.method == 'POST':
        form = SubmissionForm(request.POST, request.FILES)
        if form.is_valid():
            file = Submission(molecule_file=request.FILES['molecule_file'])
            file.juser = user_name
            file.jstatus = 'Queued'
            file.save()
            molecule_file = request.FILES['molecule_file']
            cm = request.POST.get('charge_method')
            nc = request.POST.get('net_charge')
            ml = request.POST.get('multiplicity')
            at = request.POST.get('atom_type')
            mf = molecule_file.name
            mfs = str(mf)
            task_id = uuid()
            file.jcelery_id = task_id
            name = ((str(mfs)).split('_')[0])
            file.jname = ((str(name)).split('.')[0])
            file.save()
            process_task = process.apply_async((user_name, cm, nc, ml, at, mfs, task_id), task_id=task_id)
        else:
            return render(request, 'submit.html', locals())
    return HttpResponseRedirect('/status/')


def callStatusFunc(request):
    if request.method == 'POST':
        func = request.POST.get('func')
        jpid = request.POST.get('jpid')
        
        if func == 'download':
            zip_name = Submission.objects.get(jcelery_id=jpid)
            zip_filename = zip_name.jzipped
            zip_path = acpypesetting.MEDIA_ROOT
            os.chdir(acpypesetting.MEDIA_ROOT)
            zipfile = open(zip_filename, 'rb')
            response = HttpResponse(zipfile, content_type='application/zip')
            name_zipfile = ((str(zip_filename)).split('_')[3])
            response['Content-Disposition'] = 'attachment; filename={}'.format(name_zipfile)
            return response

        elif func == 'log':
            log = Submission.objects.get(jcelery_id=jpid)
            fname = log.jlog
            fuser = log.juser
            fmol = log.molecule_file
            fdata = log.date
            fdata_str = fdata.strftime(' %a %b %d %H:%M %Y')
            os.chdir(acpypesetting.MEDIA_ROOT)
            pageFile = open(fname, "r")
            pageText = pageFile.read();
            pageFile.close()
            job = str(fuser) + " | " + str(fmol) + " | " + str(fdata_str)
            return render_to_response('view_log.html', {'file':pageText, 'jobId':job})

        elif func == 'delete':
            job = Submission.objects.get(jcelery_id=jpid)
            folder_name = job.usr_folder
            job.jstatus = "Deleted"
            job.save()
            os.chdir(acpypesetting.MEDIA_ROOT)
            rmdir = str(acpypesetting.MEDIA_ROOT + "/" + folder_name)
            try:
                shutil.rmtree(rmdir)
            except:
                pass

        elif func == 'cancel':
            job = Submission.objects.get(jcelery_id=jpid)
            mol = job.molecule_file
            app.control.revoke(jpid)
            job.jstatus = "Cancelled"
            job.save()
            os.chdir(acpypesetting.MEDIA_ROOT)

            if os.path.exists(mol):
                os.remove(mol)
            else:
                pass

        elif func == 'delete_db':
            Submission.objects.get(jcelery_id=jpid).delete()
            return HttpResponseRedirect('/adminstatus/')
    return HttpResponseRedirect('/status/')


class input(CreateView):

    template_name = 'submit.html'
    model = Submission
    fields = ('molecule_file', 'charge_method', 'net_charge', 'multiplicity', 'atom_type')


class status(ListView):
    model = Submission
    template_name = 'status.html'

    def get_context_data(self, **kwargs):
        data = super().get_context_data(**kwargs)
        data['is_running'] = Submission.objects.filter(juser=self.request.user, jstatus='Running').exists() or Submission.objects.filter(juser=self.request.user, jstatus='Queued').exists()
        return data

    def get_queryset(self):
        return Submission.objects.filter(juser=self.request.user).exclude(jstatus='Deleted').exclude(jstatus='Deleted_by_time')


class adminstatus(ListView):
    model = Submission
    template_name = 'status.html'

    def get_queryset(self):
        return Submission.objects.all()


def signup(request):
    if request.method == 'POST':
        form = SignUpForm(request.POST)
        if form.is_valid():
            user = form.save(commit=False)
            user.is_active = False
            user.save()
            current_site = get_current_site(request)
            mail_subject = 'Acpype Server Activate your account.'
            message = render_to_string('acc_active_email.html', {
                'user': user,
                'domain': current_site.domain,
                'uid':urlsafe_base64_encode(force_bytes(user.pk)).decode(),
                'token':account_activation_token.make_token(user),
            })
            to_email = form.cleaned_data.get('email')
            email = EmailMessage(
                        mail_subject, message, to=[to_email]
            )
            email.send()
            return render(request, 'confirm.html')
    else:
        form = SignUpForm()
    return render(request, 'signup.html', {'form': form})

def activate(request, uidb64, token):
    try:
        uid = force_text(urlsafe_base64_decode(uidb64))
        user =MyUser.objects.get(pk=uid)
    except(TypeError, ValueError, OverflowError, User.DoesNotExist):
        user = None
    if user is not None and account_activation_token.check_token(user, token):
        user.is_active = True
        user.save()
        login(request, user)
        # return redirect('home')
        return render(request, 'thanks.html')
    else:
        return render(request, 'invalid.html')
