"""Browser-dev fallback file picker endpoints.

The installed desktop app should use the Tauri native dialog bridge. These
tkinter-backed endpoints exist for browser-only development sessions and are
deprecated because tkinter requires an interactive desktop session and is not
appropriate for headless or service-style deployments.
"""

from tkinter import TclError, Tk, filedialog

from fastapi import APIRouter, HTTPException, status

from app.domain.models import FilePickResponse, FolderPickResponse

router = APIRouter(prefix="/folders", tags=["folders"])


@router.post(
    "/pick",
    response_model=FolderPickResponse,
    deprecated=True,
    summary="Pick a folder (browser-dev fallback)",
)
def pick_folder() -> FolderPickResponse:
    """Open a tkinter folder picker for browser-only development sessions."""
    root = None
    try:
        root = Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        selected_path = filedialog.askdirectory(title="Select documentation folder")
    except TclError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "The browser-dev folder picker fallback is unavailable because "
                "tkinter cannot open a desktop dialog in this session."
            ),
        ) from error
    finally:
        if root is not None:
            root.destroy()
    return FolderPickResponse(path=selected_path or None)


@router.post(
    "/pick-files",
    response_model=FilePickResponse,
    deprecated=True,
    summary="Pick files (browser-dev fallback)",
)
def pick_files() -> FilePickResponse:
    """Open a tkinter file picker for browser-only development sessions."""
    root = None
    try:
        root = Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        selected_paths = filedialog.askopenfilenames(title="Select documentation files")
    except TclError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "The browser-dev file picker fallback is unavailable because "
                "tkinter cannot open a desktop dialog in this session."
            ),
        ) from error
    finally:
        if root is not None:
            root.destroy()
    return FilePickResponse(paths=list(selected_paths))

