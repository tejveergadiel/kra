import streamlit as st
import ibm_boto3
from ibm_botocore.client import Config, ClientError
import os
from dotenv import load_dotenv
from datetime import datetime

load_dotenv()

# ── Page config ──────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="IBM COS File Uploader",
    page_icon="☁️",
    layout="centered",
    initial_sidebar_state="collapsed",
)

# ── CSS ───────────────────────────────────────────────────────────────────────
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap');
    .stApp { background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); font-family: 'Inter', sans-serif; }
    #MainMenu { visibility: hidden; }
    footer { visibility: hidden; }
    div[data-testid="stToolbar"] { visibility: hidden; }
    .main-card {
        background: rgba(255,255,255,0.96);
        border-radius: 20px;
        padding: 2.5rem;
        margin: 2rem auto;
        max-width: 720px;
        box-shadow: 0 20px 40px rgba(0,0,0,0.12);
    }
    .main-title {
        text-align: center;
        font-size: 2.4rem;
        font-weight: 800;
        color: #1a1a2e;
        margin-bottom: 0.3rem;
    }
    .subtitle {
        text-align: center;
        color: #57606a;
        font-size: 1rem;
        margin-bottom: 2rem;
    }
    .stButton > button {
        background: linear-gradient(135deg, #667eea, #764ba2) !important;
        color: white !important;
        border: none !important;
        border-radius: 12px !important;
        font-size: 1rem !important;
        font-weight: 600 !important;
        height: 52px !important;
        width: 100% !important;
        transition: all 0.25s ease !important;
    }
    .stButton > button:hover {
        transform: translateY(-3px) !important;
        box-shadow: 0 10px 25px rgba(102,126,234,0.35) !important;
    }
    .footer {
        text-align: center;
        color: rgba(255,255,255,0.75);
        font-size: 0.85rem;
        margin-top: 2rem;
    }
</style>
""", unsafe_allow_html=True)


# ── COS helpers ───────────────────────────────────────────────────────────────
def get_cos_client():
    """Build an IBM COS resource client using IAM OAuth."""
    return ibm_boto3.resource(
        "s3",
        ibm_api_key_id=os.getenv("COS_API_KEY_ID"),
        ibm_service_instance_id=os.getenv("COS_INSTANCE_CRN"),
        config=Config(signature_version="oauth"),
        endpoint_url=os.getenv("COS_ENDPOINT"),
    )


def upload_file_to_cos(file_bytes: bytes, object_key: str, content_type: str) -> bool:
    """Upload raw bytes to COS. Returns True on success."""
    cos    = get_cos_client()
    bucket = os.getenv("COS_BUCKET_NAME", "")
    cos.Object(bucket, object_key).put(Body=file_bytes, ContentType=content_type)
    return True


def list_cos_files(prefix: str) -> list[dict]:
    """List objects under *prefix* in the configured bucket."""
    cos = get_cos_client()
    bucket = os.getenv("COS_BUCKET_NAME")
    bucket_obj = cos.Bucket(bucket)
    items = []
    for obj in bucket_obj.objects.filter(Prefix=prefix):
        items.append({
            "name": obj.key.replace(prefix, "", 1).lstrip("/"),
            "key": obj.key,
            "size_kb": round(obj.size / 1024, 1),
            "last_modified": obj.last_modified.strftime("%Y-%m-%d %H:%M UTC"),
        })
    return items


# ── Content-type map ─────────────────────────────────────────────────────────
CONTENT_TYPES = {
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".xls":  "application/vnd.ms-excel",
    ".csv":  "text/csv",
}

# ── COS destination folder ────────────────────────────────────────────────────
COS_FOLDER = os.getenv("COS_BUCKET_PATH_CRM", "kra/").rstrip("/") + "/"


def ensure_cos_folder(folder_key: str) -> None:
    """Create a zero-byte folder placeholder in the bucket if it doesn't exist."""
    cos    = get_cos_client()
    bucket = os.getenv("COS_BUCKET_NAME", "")
    try:
        cos.Object(bucket, folder_key).load()
    except ClientError as e:
        if e.response["Error"]["Code"] in ("404", "NoSuchKey"):
            cos.Object(bucket, folder_key).put(Body=b"", ContentType="application/x-directory")
        # Any other error is surfaced later during actual uploads


# ── UI ────────────────────────────────────────────────────────────────────────
st.markdown('<div class="main-card">', unsafe_allow_html=True)

st.markdown('<div class="main-title">☁️ IBM COS File Uploader</div>', unsafe_allow_html=True)
st.markdown(
    '<div class="subtitle">Upload <strong>Excel / CSV</strong> files to IBM Cloud</div>',
    unsafe_allow_html=True,
)

# ── Env-var sanity check ──────────────────────────────────────────────────────
required_vars = ["COS_API_KEY_ID", "COS_ENDPOINT", "COS_INSTANCE_CRN", "COS_BUCKET_NAME"]
missing = [v for v in required_vars if not os.getenv(v)]
if missing:
    st.error(f"⚠️ Missing environment variable(s): `{'`, `'.join(missing)}`\n\nPlease set them in your `.env` file.")
    st.stop()

# Ensure the kra/ folder exists in the bucket
try:
    ensure_cos_folder(COS_FOLDER)
except Exception:
    pass  # non-fatal; upload errors are reported per-file

with st.expander("🔍 IAM Permission Test", expanded=False):
    if st.button("🧪 Test bucket access"):
        cos_test = get_cos_client()
        bucket   = os.getenv("COS_BUCKET_NAME", "")

        # 1. Test LIST (Reader)
        try:
            list(cos_test.Bucket(bucket).objects.limit(1))
            st.success("✅ LIST objects — allowed (Reader role present)")
        except Exception as e:
            st.error(f"❌ LIST objects — denied: {e}")

        # 2. Test PUT (Writer)
        test_key = f"{COS_FOLDER}_permission_test_.tmp"
        try:
            cos_test.Object(bucket, test_key).put(Body=b"test", ContentType="text/plain")
            st.success("✅ PUT object — allowed (Writer role present)")
            # clean up
            cos_test.Object(bucket, test_key).delete()
        except Exception as e:
            st.error(f"❌ PUT object — denied: {e}")
            st.warning("👉 Your API key has **no Writer role** on this bucket. See fix below.")
            st.info(
                "**Fix in IBM Cloud:**\n"
                "1. Go to **cloud.ibm.com → Resource List → Cloud Object Storage**\n"
                "2. Click your COS instance → **Service credentials → New credential**\n"
                "3. Set role to **Writer** (or Manager)\n"
                "4. Expand the new credential → copy the `apikey` value\n"
                "5. Paste it as `COS_API_KEY_ID` in your `.env` and restart the app"
            )

# ── Upload section ────────────────────────────────────────────────────────────
st.subheader("📤 Upload Files")

uploaded_files = st.file_uploader(
    "Choose one or more Excel / CSV files",
    type=["xlsx", "xls", "csv"],
    accept_multiple_files=True,
    help="Accepted formats: .xlsx, .xls, .csv",
)

target_folder = COS_FOLDER

if uploaded_files:
    st.markdown(f"**{len(uploaded_files)} file(s) selected:**")
    for uf in uploaded_files:
        ext = os.path.splitext(uf.name)[1].lower()
        size_kb = round(uf.size / 1024, 1)
        st.markdown(f"- `{uf.name}` — {size_kb} KB")

    st.markdown("")

    if st.button("🚀 Upload to IBM Cloud"):
        success_count = 0
        fail_count = 0

        for uf in uploaded_files:
            ext = os.path.splitext(uf.name)[1].lower()
            content_type = CONTENT_TYPES.get(ext, "application/octet-stream")
            object_key = target_folder + uf.name

            with st.spinner(f"Uploading `{uf.name}` …"):
                try:
                    file_bytes = uf.read()
                    upload_file_to_cos(file_bytes, object_key, content_type)
                    st.success(f"✅ `{uf.name}` → `{object_key}`")
                    success_count += 1
                except ClientError as e:
                    err      = e.response.get("Error", {})
                    code     = err.get("Code", "Unknown")
                    message  = err.get("Message", str(e))
                    host_id  = e.response.get("ResponseMetadata", {}).get("HostId", "—")
                    req_id   = e.response.get("ResponseMetadata", {}).get("RequestId", "—")
                    st.error(f"❌ `{uf.name}` failed: **{code}** — {message}")
                    with st.expander("📋 Full error details", expanded=True):
                        st.code(
                            f"Error Code    : {code}\n"
                            f"Message       : {message}\n"
                            f"Request ID    : {req_id}\n"
                            f"Host ID       : {host_id}\n"
                            f"HTTP Status   : {e.response.get('ResponseMetadata', {}).get('HTTPStatusCode', '—')}\n"
                            f"Bucket        : {os.getenv('COS_BUCKET_NAME')}\n"
                            f"Object key    : {object_key}\n"
                            f"Endpoint      : {os.getenv('COS_ENDPOINT')}\n"
                            f"CRN (first40) : {os.getenv('COS_INSTANCE_CRN','')[:40]}"
                        )
                    fail_count += 1
                except Exception as e:
                    import traceback
                    st.error(f"❌ `{uf.name}` unexpected error: {type(e).__name__}: {e}")
                    with st.expander("📋 Traceback", expanded=True):
                        st.code(traceback.format_exc())
                    fail_count += 1

        if success_count:
            st.balloons()
            st.info(
                f"**Upload complete** — {success_count} succeeded"
                + (f", {fail_count} failed" if fail_count else "")
            )

st.divider()

# ── View existing files ───────────────────────────────────────────────────────
st.subheader("📂 Files")

col_refresh, _ = st.columns([1, 3])
with col_refresh:
    refresh = st.button("🔄 Refresh list")

if refresh or st.session_state.get("show_files"):
    st.session_state["show_files"] = True
    try:
        with st.spinner("Fetching file list…"):
            prefix = target_folder if "target_folder" in dir() else COS_FOLDER
            files = list_cos_files(prefix)

        if files:
            st.markdown(f"**{len(files)} file(s) found:**")
            for f in files:
                st.markdown(
                    f"- 📄 `{f['name']}` — {f['size_kb']} KB — _{f['last_modified']}_"
                )
        else:
            st.info("No files found in this folder yet.")
    except Exception as e:
        st.error(f"Could not list files: {e}")

st.markdown('</div>', unsafe_allow_html=True)

st.markdown(
    '<div class="footer">IBM Cloud Object Storage Uploader · Milestone Project</div>',
    unsafe_allow_html=True,
)
