"""
Collaborators: HTML presentations shown in pages (core.presentations).

GET, POST /api/v1.0/presentations/?document=<id>   a page's; add one ({document,
    title, link} as JSON, or {document, title, file} as a form)
GET, PATCH, DELETE /api/v1.0/presentations/<id>/   what it is; rename it or
    link it elsewhere ({title, link}); remove it
POST /api/v1.0/presentations/<id>/file/            a new version ({file},
    with its PDF twin or not: {pdf} or {pdf_link})
POST, DELETE /api/v1.0/presentations/<id>/pdf-file/ the PDF twin of what it
    shows now ({file}, or {link} as JSON); without it
GET  /api/v1.0/presentations/<id>/slides/          its PDF twin as it is
GET  /api/v1.0/presentations/<id>/content/         its HTML, as text
GET  /api/v1.0/presentations/<id>/versions/        its stored versions
POST /api/v1.0/presentations/<id>/versions/<version id>/restore/
GET  /api/v1.0/presentations/<id>/pdf/?tz=<zone>   its PDF, always current
GET  /api/v1.0/presentations/storage/              what I store, and my limit
GET  /api/v1.0/presentations/guide/                how to make them (for AIs)
POST /api/v1.0/presentations/upload/<token>/       a file sent to a one-time
    address (AI assistants: `curl -F file=@deck.html -F pdf=@deck.pdf
    <address>`)
"""

from django.conf import settings
from django.http import HttpResponse
from django.utils.encoding import iri_to_uri
from django.utils.translation import gettext as _

import rest_framework as drf
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.views import APIView

from core import models, presentation_guide
from core import presentations as core_presentations
from core.api import permissions
from core.presentations import PresentationError


def _readable(user, pk):
    """A presentation the person may see, or 404."""
    presentation = (
        models.Presentation.objects.select_related("document", "current")
        .filter(pk=pk)
        .first()
    )
    if presentation is None or not core_presentations.can_read(user, presentation):
        raise drf.exceptions.NotFound()
    return presentation


def _editable(user, pk):
    """A presentation the person may change, else 404 or 403."""
    presentation = _readable(user, pk)
    if not core_presentations.can_edit(user, presentation):
        raise drf.exceptions.PermissionDenied()
    return presentation


def _refused(err):
    return drf.exceptions.ValidationError({"detail": str(err)})


def _uploaded_text(request):
    """The text of the file in a form, or a clear refusal."""
    # the nested form parser leaves files in the data
    upload = request.data.get("file") or request.FILES.get("file")
    if upload is None or isinstance(upload, str):
        raise drf.exceptions.ValidationError({"detail": _("Choose an HTML file.")})
    limit = settings.COLLABORATORS_PRESENTATION_MAX_BYTES
    if upload.size > limit:
        raise drf.exceptions.ValidationError(
            {
                "detail": _("A presentation can be up to {size}.").format(
                    size=core_presentations.megabytes(limit)
                )
            }
        )
    return upload.read()


def _given_pdf(request, field="pdf", link_field="pdf_link"):
    """The PDF twin sent with a form (a file, or a link), checked; or None."""
    upload = request.data.get(field) or request.FILES.get(field)
    link = request.data.get(link_field) or None
    if upload is not None and isinstance(upload, str):
        upload = None
    if upload is None and not link:
        return None
    limit = settings.COLLABORATORS_PRESENTATION_PDF_MAX_BYTES
    if upload is not None and upload.size > limit:
        raise drf.exceptions.ValidationError(
            {
                "detail": _("A presentation's PDF can be up to {size}.").format(
                    size=core_presentations.megabytes(limit)
                )
            }
        )
    try:
        return core_presentations.prepare_pdf(
            data=upload.read() if upload is not None else None, link=link
        )
    except PresentationError as err:
        raise _refused(err) from err


class PresentationListView(APIView):
    """A page's presentations; adding one."""

    def get_permissions(self):
        if self.request.method == "GET":
            return [AllowAny()]
        return [permissions.IsAuthenticated()]

    def get(self, request):
        """The presentations of a page one reads."""
        document = models.Document.objects.filter(
            pk=request.query_params.get("document")
        ).first()
        if document is None or not document.get_abilities(request.user).get("retrieve"):
            raise drf.exceptions.NotFound()
        return drf.response.Response(
            [
                core_presentations.describe(presentation, request.user)
                for presentation in document.presentations.select_related(
                    "document", "current"
                ).order_by("created_at")
            ]
        )

    def post(self, request):
        """Add one to a page one edits: an HTML file, or a link to one."""
        document = models.Document.objects.filter(
            pk=request.data.get("document")
        ).first()
        if document is None or not document.get_abilities(request.user).get("retrieve"):
            raise drf.exceptions.NotFound()
        has_file = bool(request.data.get("file") or request.FILES.get("file"))
        html = _uploaded_text(request) if has_file else None
        pdf = _given_pdf(request)
        try:
            presentation = core_presentations.create(
                request.user,
                document,
                title=request.data.get("title") or "",
                html=html,
                link=request.data.get("link") or None,
                pdf=pdf,
            )
        except PresentationError as err:
            raise _refused(err) from err
        return drf.response.Response(
            core_presentations.describe(presentation, request.user),
            status=status.HTTP_201_CREATED,
        )


class PresentationDetailView(APIView):
    """One presentation: what it is, renaming or relinking it, removing it."""

    def get_permissions(self):
        if self.request.method == "GET":
            return [AllowAny()]
        return [permissions.IsAuthenticated()]

    def get(self, request, pk):
        """What the block shows around it."""
        return drf.response.Response(
            core_presentations.describe(_readable(request.user, pk), request.user)
        )

    def patch(self, request, pk):
        """A new title, or a new link (the address stays the same)."""
        presentation = _editable(request.user, pk)
        try:
            core_presentations.replace(
                request.user,
                presentation,
                link=request.data.get("link") or None,
                title=request.data.get("title"),
            )
        except PresentationError as err:
            raise _refused(err) from err
        return drf.response.Response(
            core_presentations.describe(presentation, request.user)
        )

    def delete(self, request, pk):
        """It goes, with its stored files; the page's block says so."""
        presentation = _readable(request.user, pk)
        if not core_presentations.can_remove(request.user, presentation):
            raise drf.exceptions.PermissionDenied()
        core_presentations.remove(presentation)
        return drf.response.Response(status=status.HTTP_204_NO_CONTENT)


class PresentationFileView(APIView):
    """A new version, from an HTML file."""

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk):
        """Stored and shown at once, at the same address."""
        presentation = _editable(request.user, pk)
        html = _uploaded_text(request)
        try:
            core_presentations.replace(
                request.user,
                presentation,
                html=html,
                title=request.data.get("title"),
                pdf=_given_pdf(request),
            )
        except PresentationError as err:
            raise _refused(err) from err
        return drf.response.Response(
            core_presentations.describe(presentation, request.user)
        )


class PresentationPdfFileView(APIView):
    """The PDF twin of what a presentation shows now: added, or removed."""

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk):
        """A PDF file ({file}), or a link to one ({link}), in place of any."""
        presentation = _editable(request.user, pk)
        pdf = _given_pdf(request, field="file", link_field="link")
        if pdf is None:
            raise drf.exceptions.ValidationError({"detail": _("Choose a PDF file.")})
        try:
            core_presentations.attach_pdf(request.user, presentation, pdf)
        except PresentationError as err:
            raise _refused(err) from err
        return drf.response.Response(
            core_presentations.describe(presentation, request.user)
        )

    def delete(self, request, pk):
        """Without it: "Export to PDF" photographs the slides again."""
        presentation = _editable(request.user, pk)
        core_presentations.remove_pdf(presentation)
        return drf.response.Response(
            core_presentations.describe(presentation, request.user)
        )


class PresentationSlidesView(APIView):
    """Its PDF twin as it is, for the block's "Slides" tab."""

    permission_classes = [AllowAny]

    def get(self, request, pk):
        """Only one made for what it shows now; 404 otherwise."""
        presentation = _readable(request.user, pk)
        state, pdf = core_presentations.twin(presentation)
        if state != "current":
            raise drf.exceptions.NotFound()
        try:
            data = core_presentations.pdf_data(pdf)
        except PresentationError as err:
            return HttpResponse(
                str(err), status=status.HTTP_502_BAD_GATEWAY, content_type="text/plain"
            )
        response = HttpResponse(data, content_type="application/pdf")
        response["Content-Security-Policy"] = "default-src 'none'; sandbox"
        response["Cache-Control"] = "private, no-cache"
        return response


class PresentationGuideView(APIView):
    """How to make presentations for Collaborators, to give to one's AI."""

    permission_classes = [AllowAny]

    def get(self, request):
        """The guide's text (Markdown)."""
        return drf.response.Response({"guide": presentation_guide.GUIDE})


class PresentationContentView(APIView):
    """
    The HTML shown now, as plain text that no browser runs: the page puts it
    in its sealed frame.
    """

    permission_classes = [AllowAny]

    def get(self, request, pk):
        """The current version's HTML, or the linked file's."""
        presentation = _readable(request.user, pk)
        try:
            text = core_presentations.html_of(presentation)
        except PresentationError as err:
            return HttpResponse(
                str(err), status=status.HTTP_502_BAD_GATEWAY, content_type="text/plain"
            )
        response = HttpResponse(text, content_type="text/plain; charset=utf-8")
        response["Content-Security-Policy"] = "default-src 'none'; sandbox"
        response["Cache-Control"] = "private, no-cache"
        return response


class PresentationVersionsView(APIView):
    """The stored versions of a presentation, newest first."""

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, pk):
        """Each with its size, date and who uploaded it."""
        presentation = _editable(request.user, pk)
        return drf.response.Response(
            [
                {
                    "id": str(version.pk),
                    "size": version.size,
                    "created_at": version.created_at.isoformat(),
                    "uploaded_by": version.uploaded_by.full_name
                    or version.uploaded_by.short_name
                    if version.uploaded_by
                    else "",
                    "current": version.pk == presentation.current_id,
                    "has_pdf": hasattr(version, "pdf"),
                }
                for version in presentation.versions.select_related(
                    "uploaded_by", "pdf"
                )
            ]
        )


class PresentationRestoreView(APIView):
    """Show an earlier version again."""

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk, version_id):
        """It becomes the current one; nothing is removed."""
        presentation = _editable(request.user, pk)
        try:
            core_presentations.restore(presentation, version_id)
        except PresentationError as err:
            raise _refused(err) from err
        return drf.response.Response(
            core_presentations.describe(presentation, request.user)
        )


class PresentationPdfView(APIView):
    """
    The PDF of the current version, for whoever reads the page, at an address
    that never changes; a page after the cover gives the date it was made
    (in the zone given, `?tz=Europe/Paris`) and that address again.
    """

    permission_classes = [AllowAny]
    throttle_scope = "presentation_pdf"

    def get(self, request, pk):
        """Made each time, by a browser stepping through the slides."""
        presentation = _readable(request.user, pk)
        try:
            pdf = core_presentations.render_pdf(
                presentation, zone_name=request.query_params.get("tz") or ""
            )
        except PresentationError as err:
            return HttpResponse(
                str(err),
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
                content_type="text/plain; charset=utf-8",
            )
        response = HttpResponse(pdf, content_type="application/pdf")
        name = core_presentations.file_name(presentation)
        response["Content-Disposition"] = (
            f"attachment; filename*=UTF-8''{iri_to_uri(name).replace(' ', '%20')}"
        )
        response["Cache-Control"] = "private, no-store"
        return response


class PresentationStorageView(APIView):
    """What one stores of presentations, and one's limit."""

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        """Used and allowed, in bytes, and each presentation one stores."""
        user = request.user
        mine = {}
        for version in models.PresentationVersion.objects.filter(
            uploaded_by=user
        ).select_related("presentation__document"):
            presentation = version.presentation
            entry = mine.setdefault(
                presentation.pk,
                {
                    "id": str(presentation.pk),
                    "title": presentation.title,
                    "page": {
                        "id": str(presentation.document_id),
                        "title": presentation.document.title,
                    },
                    "size": 0,
                    "can_remove": core_presentations.can_remove(user, presentation),
                },
            )
            entry["size"] += version.size
        for pdf in models.PresentationPdf.objects.filter(
            uploaded_by=user
        ).select_related("presentation__document"):
            presentation = pdf.presentation
            entry = mine.setdefault(
                presentation.pk,
                {
                    "id": str(presentation.pk),
                    "title": presentation.title,
                    "page": {
                        "id": str(presentation.document_id),
                        "title": presentation.document.title,
                    },
                    "size": 0,
                    "can_remove": core_presentations.can_remove(user, presentation),
                },
            )
            entry["size"] += pdf.size
        return drf.response.Response(
            {
                "used": core_presentations.used_storage(user),
                "limit": core_presentations.storage_limit(),
                "presentations": sorted(
                    mine.values(), key=lambda entry: -entry["size"]
                ),
            }
        )


class PresentationUploadView(APIView):
    """A file sent to a one-time upload address: the address is the key."""

    authentication_classes = []
    permission_classes = [AllowAny]

    def post(self, request, token):
        """
        Stored as the new version, with its PDF twin (`pdf`) or not, credited
        to whoever got the address; or only a PDF for what it shows now. The
        answer says what the file misses of the guide.
        """
        # the files first: a refused one doesn't use up the address
        has_file = bool(request.data.get("file") or request.FILES.get("file"))
        text = _uploaded_text(request) if has_file else None
        pdf = _given_pdf(request)
        if text is None and pdf is None:
            raise drf.exceptions.ValidationError({"detail": _("Choose an HTML file.")})
        try:
            presentation, user = core_presentations.use_upload_address(token)
            core_presentations.replace(user, presentation, html=text, pdf=pdf)
        except PresentationError as err:
            raise _refused(err) from err
        return drf.response.Response(
            {
                **core_presentations.describe(presentation, user),
                "checks": core_presentations.checks_of(presentation),
            }
        )
