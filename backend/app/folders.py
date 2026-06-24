from tkinter import TclError, Tk, filedialog

from fastapi import APIRouter, HTTPException, status

from app.models import FilePickResponse, FolderPickResponse

router = APIRouter(prefix="/folders", tags=["folders"])


@router.post("/pick", response_model=FolderPickResponse)
def pick_folder() -> FolderPickResponse:
    root = None
    try:
        root = Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        selected_path = filedialog.askdirectory(title="Select documentation folder")
    except TclError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Native folder picker is unavailable in this session.",
        ) from error
    finally:
        if root is not None:
            root.destroy()
    return FolderPickResponse(path=selected_path or None)


@router.post("/pick-files", response_model=FilePickResponse)
def pick_files() -> FilePickResponse:
    root = None
    try:
        root = Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        selected_paths = filedialog.askopenfilenames(title="Select documentation files")
    except TclError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Native file picker is unavailable in this session.",
        ) from error
    finally:
        if root is not None:
            root.destroy()
    return FilePickResponse(paths=list(selected_paths))
