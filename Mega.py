from datetime import date, datetime, timedelta
import glob
import io
import os
import re
import tempfile
import warnings

import gdown
import gspread
import pandas as pd
import streamlit as st
from stqdm import stqdm
 
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload, MediaIoBaseDownload

from gspread_dataframe import get_as_dataframe, set_with_dataframe
from oauth2client.service_account import ServiceAccountCredentials

warnings.filterwarnings('ignore')


SCOPES = ['https://www.googleapis.com/auth/drive']


def save_upload(fileupload, fileType = None):
    temp_dir = tempfile.mkdtemp()
    tmp_path = os.path.join(temp_dir, fileupload.name)

    with open(tmp_path, "wb") as f:
        f.write(fileupload.getvalue())
   
    return tmp_path

def next_sunday():
    """
    Returns the date of the upcoming Sunday in 'YYYY-MM-DD' format.
    If today is already a Sunday, returns today's date.
    """
    today = date.today()
    # Monday=0 ... Sunday=6
    days_until_sunday = (6 - today.weekday()) % 7
    result = today + timedelta(days=days_until_sunday)
    return result.strftime("%Y-%m-%d")

def getGdriveService(GdriveCredentials, delegated_user=None):
    # Authenticates with Google Drive using a service account file
    # Pass delegated_user="someone@yourdomain.com" to impersonate a real user (needed if
    # uploading/downloading against a personal My Drive folder rather than a Shared Drive)

    creds = service_account.Credentials.from_service_account_file(GdriveCredentials, scopes=SCOPES)

    if delegated_user:
        creds = creds.with_subject(delegated_user)

    return build('drive', 'v3', credentials=creds)

def getFilesList(parent_folder_id, service):
    # Retrieves ALL files/folders within a parent folder (paginated, Shared-Drive aware)
    file_list = []
    page_token = None
    while True:
        results = service.files().list(
            q=f"'{parent_folder_id}' in parents and trashed=false",
            fields="nextPageToken, files(id, name)",
            pageToken=page_token,
            supportsAllDrives=True,
            includeItemsFromAllDrives=True,
            corpora='allDrives'
        ).execute()
        file_list.extend(results.get('files', []))
        page_token = results.get('nextPageToken')
        if not page_token:
            break
    return file_list

def getSubfolderId(parent_folder_id, folder_name, service):
    # Looks up a named subfolder's ID within a parent folder
    for item in getFilesList(parent_folder_id, service):
        if item['name'] == folder_name:
            return item['id']
    return None

# ---------- Download ----------

def download_file(service, file_id, file_name, clear):
    # Downloads a single file straight to disk, with a Streamlit progress bar
    if file_name not in st.session_state or clear:
        
        request = service.files().get_media(fileId=file_id, supportsAllDrives=True)

        progress_bar = st.progress(0, text=f"Downloading {file_name}...")

        with open(file_name, 'wb') as f:
            downloader = MediaIoBaseDownload(fd=f, request=request)
            done = False
            while not done:
                status, done = downloader.next_chunk()
                if status:
                    pct = int(status.progress() * 100)
                    progress_bar.progress(pct, text=f"Downloading {file_name}... {pct}%")

        progress_bar.progress(100, text=f"{file_name} downloaded")

        st.session_state[file_name] = file_name
        return file_name

    else:
        return st.session_state[file_name]

def getFilefromGdrive(folder_id, service, ProcessParameter, clear):
    # Downloads all files from a named subfolder within folder_id
    subfolder_id = getSubfolderId(folder_id, ProcessParameter, service)
    file_list = getFilesList(subfolder_id, service)

    filePaths = []
    for f in  file_list :
        download_file(service, f['id'], f['name'], clear)
        filePaths.append(f['name'])

    return filePaths, service


def getSheet(sheet_id, sheet_name, credential_Upload):
  scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
  creds = ServiceAccountCredentials.from_json_keyfile_name(credential_Upload, scope)
  client = gspread.authorize(creds)

  workbook = client.open_by_key(sheet_id)
  values = workbook.worksheet(sheet_name).get_all_values()
  records = workbook.worksheet(sheet_name).get_all_records()
  # sheet_name = datetime.now().strftime("%b-%Y")

  # Read the downloaded XLSX file into a pandas DataFrame
  try:
      paymentSlugs = pd.DataFrame(values[1:], columns=values[0])
      return paymentSlugs
  except:
      return None

#Pre-Processing Payment Report and getDates Functions
def generatePaymentReport(filePath):
  paymentReport = pd.read_csv(filePath[0], sep=",", date_format="%Y-%m-%d %H:%M:%S", dayfirst=True,  low_memory=False)

  #Filter the rows
  paymentReport = paymentReport[(paymentReport["Tags"].fillna("empty").str.contains("l1") | paymentReport["Tags"].isna() )]

  #Changing the data type of phone number column
  paymentReport["Phone Number"] = paymentReport["Phone Number"].astype(str).str.replace(r"\D", "", regex=True)

  #Filtering the records according to the condition -- captured and PaymentAmountThreshold
  paymentReport = paymentReport[(paymentReport["Status"].str.strip().str.lower()  == "captured")]

  #Formatting the column as date time
  paymentReport["CreatedAt"] = pd.to_datetime(paymentReport["CreatedAt"], format = "%Y-%m-%d %H:%M:%S", exact=True, dayfirst=True, yearfirst=False)

  paymentSlugs["PaymentFunnel"] = paymentSlugs["PaymentFunnel"].apply(lambda x: pd.NA if x  == '' else x)

  paymentSlugs.dropna(subset = ["PaymentFunnel"], inplace = True, how="any")

  paymentReport = paymentReport.merge(paymentSlugs[(paymentSlugs["isExotic"] == "No")],  on="Payment Slug", how="left")

  Unmatched_Slugs = paymentReport[paymentReport["PaymentFunnel"].isna()]
  Unmatched_Slugs.to_csv("Unmatched_Slugs.csv", index=False, sep=",")

  SlugsList = sorted(paymentSlugs["PaymentFunnel"].unique().tolist())
  paymentReport = paymentReport[~paymentReport["PaymentFunnel"].isna()]

  paymentReport.drop(columns= "isExotic", inplace=True)

  return paymentReport

def getDates(Funnel):

  BatchDate[["Date", 'StartDate', 'EndDate']] = BatchDate[["Date", 'StartDate', 'EndDate']]#.astype('M8[s]')
  ExcludedTimings[["Date", 'StartDate', 'EndDate']] = ExcludedTimings[["Date", 'StartDate', 'EndDate']]#.astype('M8[s]')

  FilteredBatchDate = BatchDate[(BatchDate["Date"] == WSDate) & (BatchDate["Funnel"]  == Funnel) ]

  if len(FilteredBatchDate)>0:
    startDate = FilteredBatchDate["StartDate"].iloc[0]
    endDate = FilteredBatchDate["EndDate"].iloc[0]
  else:
    startDate = None
    endDate = None

  FilteredExcludedTimings = ExcludedTimings[(ExcludedTimings["Date"] == WSDate) & (ExcludedTimings["Funnel"]  == Funnel)]

  if len(FilteredExcludedTimings) > 0:
    excludedStartDates = FilteredExcludedTimings["StartDate"]
    excludedEndDates = FilteredExcludedTimings["EndDate"]
  else:
    excludedStartDates = None
    excludedEndDates = None

  return startDate, endDate, excludedStartDates, excludedEndDates

def CountIf(Main_File, Current_File, MFCol, CFCol, filename):

    MainFileColCleaned = MFCol.replace(" ", "") # Clean whitespace from main column name
    CurrentFileColCleaned = CFCol.replace(" ", "") # Clean whitespace from current column name

    NewColName = MainFileColCleaned[:5]+"_"+re.sub(r"\W", "", filename[:5])+"_"+CurrentFileColCleaned # Construct unique column name

    newcol = 1 # Initialize suffix counter
    while NewColName in Main_File.columns:
        NewColName = NewColName+"_"+str(newcol) # Append suffix if name exists
        newcol = newcol+1 # Increment counter

    lookup_set = set(Current_File[CFCol].astype(str).str.lower().str.strip()) # Create optimized lookup set
    Main_File.insert(loc=len(Main_File.columns), column=NewColName,
                     value=Main_File[MFCol].astype(str).str.lower().str.strip().isin(lookup_set).astype(int),
                     allow_duplicates=True) # Insert binary match column

    return Main_File, NewColName # Return modified dataframe and name

#  Generate the MEGA Report

def processMEGA(Funnels, filePath, ):
  FileList = []

  ExcludedData = []

  paymentReport = generatePaymentReport(filePath)

  FunnelCount = pd.DataFrame(columns = ["Funnel", "Count"])

  for Funnel in stqdm(Funnels):
    data = pd.DataFrame()

    startDate, endDate, excludedStartDates, excludedEndDates = getDates(Funnel)

    if startDate is not None:
      FunnelPayment = paymentReport[(paymentReport["PaymentFunnel"] == Funnel) & (paymentReport["CreatedAt"].between(startDate, endDate) )]
    else:
      FunnelPayment = paymentReport[(paymentReport["PaymentFunnel"] == Funnel)]
      st.write(f"Start Date not defined for {Funnel}.")

    FunnelPayment["Abandon Cart"] = "No"

    if excludedStartDates is not None:
      excludedStartDatesTZ = [pd.to_datetime(d) for d in excludedStartDates]
      excludedEndDatesTZ   = [pd.to_datetime(d) for d in excludedEndDates]
      st.write(f"Number of date count(s) to be exluded for {Funnel}- {len(excludedStartDates)}.")

      for start, end in zip(excludedStartDatesTZ, excludedEndDatesTZ):
          df =  FunnelPayment[FunnelPayment["CreatedAt"].between(start, end, inclusive="both")]
          df["StartDate"] = start
          df["EndDate"] = end
          data = pd.concat([data, df], axis= "rows")
          FunnelPayment = FunnelPayment[~FunnelPayment["Payment Id"].isin(df["Payment Id"])]

      st.write(f"Count of excluded rows {len(data)}.")

    if Funnel in ExcludeAmount.keys():
        FunnelPayment = FunnelPayment[~FunnelPayment["Amount"].isin(ExcludeAmount[Funnel])] # Remove specific excluded amounts
    

    FunnelPayment = FunnelPayment[FunnelPayment["Amount"] > 0]

    FunnelPayment = FunnelPayment.sort_values(by=["Amount"], ascending=False)
    FunnelPayment["EmailLC"] = FunnelPayment["Email"].str.lower().str.strip()
    FunnelPayment.drop_duplicates(subset=["EmailLC","Phone Number"], inplace=True, ignore_index=True)
    FunnelPayment.drop_duplicates(subset=["EmailLC"], inplace=True, ignore_index=True)

    FunnelPayment["Phone Number"] = FunnelPayment["Phone Number"].astype(float, errors="ignore")

    FunnelPayment.drop_duplicates(subset=["Phone Number"], inplace=True, ignore_index=True)
    FunnelPayment.drop(columns=["EmailLC"], inplace=True)

    columns = ["PaymentFunnel" , "Payment Id", "Payment Method", "Amount", "Email", "Phone Number", "Payment Slug",  "Status", "Tags", "CreatedAt", "Source", 
               "woocommerce OrderID", "Age Group", "Customer Name", "Business", "Profession (PG)", "Abandon Cart"]

    FunnelPayment = FunnelPayment[columns]

    FunnelPayment = FunnelPayment.sort_values(by=["CreatedAt"], ascending=True)
    #st.write(f"{Funnel} count = {len(FunnelPayment)}.")

    FunnelCount = pd.concat([FunnelCount, pd.DataFrame({"Funnel": [Funnel], "Count": [len(FunnelPayment)]})], axis="rows", ignore_index=True)

    if len(FunnelPayment) > 0:
      output_filename = f"{Funnel}_{WSDate}.csv"
      FileList.append(output_filename)
      FunnelPayment.to_csv(output_filename, index=False, sep=",")

    if len(data) > 0:
      output_filename = f"ExcludedData{Funnel}_.csv"
      ExcludedData.append(output_filename)
      data = data.sort_values(by=["CreatedAt"], ascending=True)
      data.to_csv(output_filename, index=False, sep=",")

  Unmatched_Slugs = pd.read_csv("Unmatched_Slugs.csv")

  if len(Unmatched_Slugs) > 0:
    try:
        Unmatched_SlugsDF = Unmatched_Slugs.loc[Unmatched_Slugs["Payment Slug_x"].str.len() < 36, "Payment Slug_x"].drop_duplicates()
    except:
        Unmatched_SlugsDF = Unmatched_Slugs.loc[Unmatched_Slugs["Payment Slug"].str.len() < 36, "Payment Slug"].drop_duplicates()
  else:
        Unmatched_SlugsDF = None


  has_ai = any(kw.startswith("AI_") for kw in FileList)
  has_bootcamp_paid = any(kw.startswith("AI BootcampPaid") for kw in FileList)
  
  # @title Remove Duplicates between AI and AI BootcampPaid
  if has_ai and has_bootcamp_paid:
    AIFilePath = [i for i in FileList if i.startswith("AI_")][0] # Locate AI CSV path
    AIBootcampPaidFilePath = [i for i in FileList if i.startswith("AI BootcampPaid")][0] # Locate Bootcamp CSV path
    AI = pd.read_csv(AIFilePath) # Load AI data
    AIBootcampPaid = pd.read_csv(AIBootcampPaidFilePath) # Load Bootcamp data

    MFCombinations = ['Email', 'Phone Number'] # Define matching columns
    AIBootcampSheetCombinations = ['Email',  'Phone Number'] # Define target matching columns

    SumColNames = [] # Initialize list for match column names

    AIBootcampPaid["Phone Number"] = AIBootcampPaid["Phone Number"].astype(str) # Stringify phone for comparison
    AI["Phone Number"] = AI["Phone Number"].astype(str) # Stringify phone for comparison

    CurrentFileSumColumns = [] # Tracks specific generated columns
    for MFCol, CFCol  in zip(MFCombinations, AIBootcampSheetCombinations):
        AI, NewColName = CountIf(AI, AIBootcampPaid, MFCol, CFCol, Funnel) # Check for overlaps
        SumColNames.append(NewColName) # Track col name
        CurrentFileSumColumns.append(NewColName) # Track for summation

    TotalColName = "Total" # Name indicator column

    AI[TotalColName] = AI[CurrentFileSumColumns].sum(axis=1).gt(0).map({True: 'Matched', False: 'Unmatched'}) # Determine if any criteria matched

    print(len(AI[AI[TotalColName] == "Matched"]))

    AI = AI[AI[TotalColName] == "Unmatched"] # Remove matched rows from AI funnel

    FunnelCount.loc[(FunnelCount["Funnel"]=="AI"), "Count"] = len(AI) # Update counts table

    AI.drop(columns=CurrentFileSumColumns+[TotalColName], inplace=True) # Remove comparison helpers

    AI.rename(columns={"Payment Slug_y": "ExoticSlugs", "Payment Slug_x": "Payment Slug"}, inplace=True) # Fix renamed columns after merge

    if len(AI) > 0:
        output_filename = f"AI_{WSDate}.csv" # Define output name
        AI.to_csv(output_filename, index=False, sep=",") # Overwrite AI file without duplicates
        print(f"AI count = {len(AI)}.")

  return FileList, ExcludedData, FunnelCount, Unmatched_SlugsDF

def updateMegaSheet(credential_Upload, sheet_id, file):
  # Authentication
  scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
  creds = ServiceAccountCredentials.from_json_keyfile_name(credential_Upload, scope)
  client = gspread.authorize(creds)

  workbook = client.open_by_key(sheet_id)

  try:  #Gets the batchname by removing splitting from the "W" part.
        df = pd.read_csv(file, sep=",")
        columns = ["CreatedAt","Customer Name", "Email", "Phone Number", "Amount", "Age Group", "Payment Slug", "Abandon Cart", "Profession (PG)"]
        MainFileBatches = file.split(".")[0].replace(f"_{WSDate}", "")
        df = df[columns]
  except:
      MainFileBatches = None

  existing_sheet_titles = [ws.title for ws in workbook.worksheets()]
  #st.write(existing_sheet_titles)

  if MainFileBatches is not None:
    if MainFileBatches not in existing_sheet_titles:
        AddNewWS = workbook.add_worksheet(title=MainFileBatches, rows='100', cols='20')
        batchData = AddNewWS # Use the newly created worksheet object
    else:
        batchData = workbook.worksheet(MainFileBatches)
        batchData.clear()

  # Ensure set_with_dataframe receives the worksheet object
    set_with_dataframe(batchData, df)
    os.unlink(file)
    st.write(f"Process Completed for {file}.")
    return True

  else:
    st.write(file)

def intilizeUpload(TotalFiles, sheet_id, credential_Upload):
    with st.status("Uploading..", expanded=True) as status:
        for file in stqdm(sorted(TotalFiles)):
            updateMegaSheet(credential_Upload, sheet_id, file)

        status.update(label="Upload Complete!!",expanded=False)

    st.success("Upload Completed!")

    st.session_state["upload_done"] = True  # mark upload as complete
    st.rerun()

def check_session_state(sheet_id  ,sessionVarName , sheet_name , credential_Upload , clear):
        if sessionVarName not in st.session_state or clear:
            st.write(f"Downloading {sessionVarName}.. ")
            st.session_state[sessionVarName] = getSheet( sheet_id, sheet_name, credential_Upload)
            return st.session_state[sessionVarName]
        else:
            return  st.session_state[sessionVarName]
    

st.set_page_config("MEGA Sheet", layout="wide")
st.header("📊 MEGA Sheet", divider=True, text_alignment="center")
WSDate =  str(st.date_input("Select the Next Sunday date",value=next_sunday()))
credential_Upload = st.file_uploader("Upload Credentials File", type = ["json"]) 
GdriveCredentials =  st.file_uploader("Upload GDrive File", type = ["json"]) 
Funnels = st.multiselect(label="Select the Funnels", options=["10xTechies", "AI", "Python", "Excel", "SMAI", "DRF", "PU", "AI TV", "AI BootcampPaid"])

col1, col2, col3 = st.columns(3)    
with col1:
    download = st.checkbox("Download MEGA", persist_state="page", key="downloadKey")

with col2:
    IncludeExcludeData = st.checkbox("Include Excluded Data?")

with col3:
   clearPreviousData = st.checkbox("Clear Data?")

if WSDate and Funnels and GdriveCredentials and credential_Upload:
    genbtn = st.button("Generate Data", type="primary", on_click=None )

# Example usage:
    if genbtn:
        if "TotalFiles" in st.session_state:
            st.session_state.pop("TotalFiles") 

        if "upload_done" in st.session_state:
            st.session_state.pop("upload_done") 

        credential_Upload = save_upload(credential_Upload)
        st.session_state["credential_Upload"] = credential_Upload

        GdriveCredentials = save_upload(GdriveCredentials)

        with st.status("Processing..", expanded=True) as status:
            service = getGdriveService(GdriveCredentials)  # or getGdriveService(delegated_user="owner@yourdomain.com")
            filePath, service = getFilefromGdrive('0AHGO663tIOm5Uk9PVA', service, WSDate, clearPreviousData)

        # @title Downloading All Sheets
        # Remove existing file if it exists to avoid conflicts
        
            paymentSlugs = check_session_state("1v0UI5B4rkWJm3N8cbqnRCa4olvwV6-h-YC2mafNYnjU","paymentSlugs", WSDate, credential_Upload, clearPreviousData) 
 
            BatchDate = check_session_state("1szfXpbxy1lITxMU53e0TqlV_PjRVGv3OKTpI1wjoegk", "BatchDate", "BatchDate", credential_Upload, clearPreviousData)
 
            ExcludedTimings = check_session_state("1szfXpbxy1lITxMU53e0TqlV_PjRVGv3OKTpI1wjoegk", "ExcludedTimings", "ExcludedTimings", credential_Upload, clearPreviousData)
 
            MegaSheetInfo = check_session_state("1szfXpbxy1lITxMU53e0TqlV_PjRVGv3OKTpI1wjoegk", "MegaSheetInfo", "MegaSheetInfo", credential_Upload, clearPreviousData)
 
            ExcludeAmount = check_session_state("1szfXpbxy1lITxMU53e0TqlV_PjRVGv3OKTpI1wjoegk", "ExcludeAmount", "ExcludedAmount", credential_Upload, clearPreviousData) # Fetch amounts to exclude

            EA = ExcludeAmount.groupby("Funnel").apply(lambda x:  x["Amount"].astype(float).unique()).reset_index() # Group and find unique float amounts
            EA.columns = ["Funnel", "Amount"] # Rename columns
            ExcludeAmount = EA.set_index("Funnel")["Amount"].to_dict() # Convert to lookup dictionary

            condition = ((MegaSheetInfo["Date"] == WSDate) & (MegaSheetInfo["InUse"] == "Yes") )
            sheet_id = MegaSheetInfo.loc[condition,  "sheet_id" ].unique()[0]

            st.session_state["sheet_id"] = sheet_id

            status.update(label="Completed!",expanded=False)

            FileList, ExcludedData, FunnelCount, Unmatched_SlugsDF = processMEGA(Funnels,filePath)

        st.dataframe(MegaSheetInfo.loc[condition, ["Date", "sheet_id"]] , hide_index=True)

        if len(Unmatched_SlugsDF) is not None:
            st.dataframe(Unmatched_SlugsDF,  hide_index=True)
         
        st.dataframe(FunnelCount, hide_index=True)
        
        TotalFiles = FileList+ExcludedData if IncludeExcludeData is True else FileList

 
        st.session_state["TotalFiles"] = TotalFiles

        if download:
            MegaFileName = rf"Mega_{WSDate}.xlsx"
             
            requiredData = TotalFiles

            buffer = io.BytesIO()
            with pd.ExcelWriter(MegaFileName, engine="xlsxwriter") as f:
                for file in stqdm(sorted(requiredData), desc="Building MEGA file"):
                    data = pd.read_csv(file)
                    data["CreatedAt"] = data["CreatedAt"].astype('M8[s]').dt.strftime("%Y-%m-%d %H:%M:%S")
                    data.to_excel(f, sheet_name=file.split("_")[0], index=False)

                FunnelCount.to_excel(f, sheet_name="FunnelCount", index=False)

            with open(MegaFileName, "rb") as f:
                st.download_button(
                    label="Save MEGA file",
                    data=f.read(),
                    file_name=MegaFileName,
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    on_click="ignore"
                )
    #Unmatched_Slugs.to_excel(f, sheet_name="Unmatched_Slugs", index=False)
    
        st.link_button(f"Go to Sheet- {sheet_id}", f"https://docs.google.com/spreadsheets/d/{sheet_id}/edit?usp=sharing", type = "secondary")

    if "TotalFiles" in st.session_state:
        if "upload_done" not in st.session_state:
            st.session_state["upload_done"] = False

        TotalFiles = st.session_state["TotalFiles"]
        sheet_id = st.session_state["sheet_id"]
        credential_Upload = st.session_state["credential_Upload"]

        if not st.session_state["upload_done"]:
            upload = st.button("Upload Data?", type="primary", key="upload")
            if upload:
                intilizeUpload(TotalFiles, sheet_id, credential_Upload)
        else:
            st.success("Upload Completed!")
                
             
else:
     with st.status("Links", expanded=False):
        col1, col2, col3, col4, col5, col6  = st.columns(6, vertical_alignment = "center",  width="stretch") 
     
        with col1:
           st.link_button("Open 10xStats", "https://10xstats.com/", width  = "stretch")
        with col2:
           st.link_button("Open DirectUS", "https://directus-production-62b2.up.railway.app/admin/users/", width  = "stretch") 
        with col3:
           st.link_button("Open MEGA Exotic", "https://megaexotic.streamlit.app/", width  = "stretch") 
        with col4:
           st.link_button("Open MEGA AC", "https://megaac.streamlit.app/", width  = "stretch") 
        with col5:
           st.link_button("Open GdriveUpload", "https://gdriveupload.streamlit.app/", width  = "stretch")
        with col6:
           st.link_button("Open PaymentSlugsUpdate", "https://paymentslugs.streamlit.app/", width  = "stretch")

