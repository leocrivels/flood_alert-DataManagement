from tkinter import *
from tkinter import filedialog
from tkinter import messagebox
from tkinter import ttk
import pyrebase
import json
import rasterio
from rasterio.mask import mask
from rasterio import features
import pprint
import numpy as np
import sys
from rasterio.enums import Resampling
import gdal, ogr, os, osr, errno
import csv
import time
import datetime
from functools import partial
import json
import csv
from datetime import datetime, timedelta
import requests
import requests_ftp
from google.cloud import storage

now = datetime.now()
backup_foldername = 'YOUR:/BACKUP/DIRECTORY/' + now.strftime("%Y-%m-%d")

def clickSelectFolder(folderEntry):
    direc = filedialog.askdirectory()
    folderEntry.set(direc)

#Get the forecast from cptec and creates a CSV
def createForecastCSV(folderEntry):
    if folderEntry.get() != '' and os.path.exists(os.path.dirname(folderEntry.get())):
        dateTimeObj = datetime.now()
        dateTimeObj = dateTimeObj - timedelta(hours=int(dateTimeObj.strftime("%H")))
        dayString = dateTimeObj.strftime("%d")
        monthString = dateTimeObj.strftime("%m")
        yearString = dateTimeObj.strftime("%Y")
        url = 'http://ftp1.cptec.inpe.br/modelos/tempo/WRF/ams_05km/recortes/grh/json/' + yearString + '/' + monthString + '/' + dayString + '/00/225.json'
        requests_ftp.monkeypatch_session()
        response = requests.get(url)
        print(response)
        data = response.text
        print(data)
        weather = json.loads(data)

        hora = int(dateTimeObj.strftime("%H"))
        print(str(hora))
        print(str(dateTimeObj))
        timestampStr = dateTimeObj.strftime("%d%b%Y %H")
        
        print('Current Timestamp : ', timestampStr)

        fileOutput = folderEntry.get()+'/forecast.csv'
        outputFile = open(fileOutput, 'w') #load csv file
        with open(fileOutput, 'w', newline='') as outputFile:
            output = csv.writer(outputFile, delimiter=',', quotechar='"', quoting=csv.QUOTE_MINIMAL)
            datasets = weather["datasets"][0]
            data = datasets["data"] #load json content
            outputFile.write("B,,PROSA\n")
            outputFile.write("C,UTC,PRECIP-INC\n")
            outputFile.write("E,,1HOUR\n")
            outputFile.write("F,,OBS\n")
            outputFile.write("Units,,MM\n")
            outputFile.write("Type,,PER-CUM\n")

            for i,row in enumerate(data):
                print(str(hora + i))
                outputFile.write(str(i+1) + "," + timestampStr + "00" +', '+ str(row["prec"]))
                outputFile.write('\n')
                dateTimeObj = dateTimeObj + timedelta(hours=1)
                timestampStr = dateTimeObj.strftime("%d%b%Y %H")

    elif folderEntry.get() == '':
        messagebox.showinfo('Error', 'Please Select the Destination Folder!')
    elif not os.path.exists(os.path.dirname(folderEntry.get())):
        messagebox.showinfo('Error', 'Destination Folder Doesn\'t Exist!')

#Downsample the raster
def downsampling( g, hires_data, factor ):
    """This function downsamples, using the **mode**, the 2D array
    `hires_data`. The datatype is assumed byte in this case, and
    you might want to change that. The output files are given by
    `fname_out`, and we downsample by a factor of 100 and 300. The
    initial GDAL dataset is `g` (this is where the data are coming
    from, and we use that to fish out the resolution, geotransform,
    etc.).

    NOTE that this is fairly specialised a function, and you might
    want to have more flexiblity by adding options to deal with
    the aggregation procedure in `gdal.RegenerateOverviews`, the
    resolutions of the aggregations you want, the datatypes, etc.
    """
    # Create an in-memory GDAL dataset to store the full resolution
    # dataset...

    total_obs = g.RasterCount
    drv = gdal.GetDriverByName( "MEM" )
    dst_ds = drv.Create("", g.RasterXSize, g.RasterYSize, 1, gdal.GDT_UInt16 )
    dst_ds.SetGeoTransform( g.GetGeoTransform())

    srs = osr.SpatialReference()
    srs.ImportFromEPSG(32721)

    dst_ds.SetProjection ( srs.ExportToWkt() )
    proj = osr.SpatialReference(wkt=g.GetProjection())

    dst_ds.GetRasterBand(1).WriteArray( hires_data.astype(float)*100 )

    geoT = g.GetGeoTransform()
    drv1 = gdal.GetDriverByName( "GTiff" )

    resampled_dir = backup_foldername + "/raster/"

    if not os.path.exists(os.path.dirname(resampled_dir)):
        try:
            os.makedirs(os.path.dirname(resampled_dir))
        except OSError as exc: # Guard against race condition
            if exc.errno != errno.EEXIST:
                raise

    resampled_filename =  resampled_dir + now.strftime("%Y-%m-%d_%H%M%S") + ".tif"

    resampled = drv1.Create( resampled_filename , int(g.RasterXSize/factor), int(g.RasterYSize/factor), 1, gdal.GDT_UInt16 )

    this_geoT = ( geoT[0], geoT[1]*factor, geoT[2], geoT[3], geoT[4], geoT[5]*factor )
    resampled.SetGeoTransform( this_geoT )
    resampled.SetProjection (srs.ExportToWkt())

    gdal.RegenerateOverviews ( dst_ds.GetRasterBand(1), [resampled.GetRasterBand(1)],'average' )

    resampled.GetRasterBand(1).SetNoDataValue ( 0 )

    return resampled_filename

#Makes the geojson of the raster's shape polygon
def makePolyGeojson(filename) :
    now = datetime.now()
    geoteste = ''
    orig_stdout = sys.stdout
    dateString = filename[filename.find('(')+1 : filename.find(')')]

    jsonBackUpName = backup_foldername + '/json/' + now.strftime("%Y-%m-%d_%H%M%S")+'.json'
    if not os.path.exists(os.path.dirname(jsonBackUpName)):
        try:
            os.makedirs(os.path.dirname(jsonBackUpName))
        except OSError as exc: # Guard against race condition
            if exc.errno != errno.EEXIST:
                raise

    f = open(jsonBackUpName, 'w')
    print(filename)
    with rasterio.open(filename) as src:
        print(
            """{   "type": "GeometryCollection",
    "geometries": ["""
        )
        geoteste = geoteste +"""{   "type": "GeometryCollection",
    "geometries": ["""
        

        mask = src.dataset_mask()

        for geom, val in rasterio.features.shapes(
                mask, transform=src.transform):

            # Transform shapes from the dataset's own coordinate
            # reference system to CRS84 (EPSG:4326).
            geom = rasterio.warp.transform_geom(
                src.crs, 'EPSG:4326', geom, precision=5)

            # Print GeoJSON shapes to stdout.
            if val > 0 :
                pprint.pprint(geom)
                geoteste = geoteste + json.dumps(geom)
                geoteste = geoteste + "\n,"
                lastline = f.tell()
                print(',')
            
        f.seek(lastline)
        """],
        "period": {
            "begin": + str(time.time()*1000) + ,
            "end": + str((time.time()+3*3600)*1000) +}
            }"""
        print("""],
        "properties": {timestamp": """ + str(time.mktime(datetime.datetime.strptime(dateString, "%d%b%Y %H %M %S").timetuple())) + """}
            }"""
        )

        geoteste = geoteste[:-1]
        geoteste = geoteste + """],
        "properties": {timestamp": """ + str(time.mktime(datetime.datetime.strptime(dateString, "%d%b%Y %H %M %S").timetuple())) + "}"
        geoteste = geoteste +"""
                
            }"""

    sys.stdout = orig_stdout
    f.close()
    return geoteste

config = {
  "apiKey": "YOR_API_KEY",
  "authDomain": "YOUR_AUTHDOMAIN",
  "databaseURL": "YOUR_DATABASE_URL",
  "storageBucket": "YOUR_STORAGEBUCKET",
  "serviceAccount": "YOUR_SERVICEACCOUNT_JSON"
}
firebase = pyrebase.initialize_app(config)
 
window = Tk()
 
window.title('Flood Alert Data')

window.geometry('720x200')
style = ttk.Style()

tab_control = ttk.Notebook(window)

tab_areas = ttk.Frame(tab_control)

tab_markers = ttk.Frame(tab_control)

tab_forecast = ttk.Frame(tab_control)

tab_control.add(tab_areas, text='Areas')

tab_control.add(tab_markers, text='Markers')

tab_control.add(tab_forecast, text='Forecast')

lbl = Label(tab_areas, text="Select the flood surface raster:", justify=LEFT,font=("Arial Bold", 24))
 
lbl.grid(column=0, row=0)

fileEntry = StringVar()

downsampling_factor = StringVar()
downsampling_factor.set('3')

#send the raster shape to firebase
def sendClicked(raster):
    if downsampling_factor.get() != '' and os.path.exists(os.path.dirname(raster.get())):
        db = firebase.database()
        
        resampled_filename = ''
        with rasterio.open(raster.get()) as src:
            print(src.crs)
            resampled_filename = downsampling( gdal.Open(raster.get()), np.array(src.read(1)), int(downsampling_factor.get()) )

        geoteste = makePolyGeojson(resampled_filename)

        db.child("polygons").push(json.loads(geoteste))

        messagebox.showinfo('Success', 'Data sent to server!')
    elif downsampling_factor.get() == '':
        messagebox.showinfo('Error', 'Missing Downsampling Factor!')
    elif not os.path.exists(os.path.dirname(raster.get())):
        messagebox.showinfo('Error', 'Missing flood surface raster!')

fileDir = Entry(tab_areas,width=40, font=("Arial", 18), textvariable=fileEntry)
fileDir.grid(column=0, row=1)

lbl2 = Label(tab_areas, text="Downsampling Factor:", justify=LEFT,font=("Arial Bold", 24))
lbl2.grid(column=0, row=2)
factorBlock = Entry(tab_areas,width=10, font=("Arial", 18), textvariable=downsampling_factor)
factorBlock.grid(column=0, row=3)

def clickSelectFile(entry):
    direc = filedialog.askopenfilename(filetypes = [('Image Files', ['.tiff', '.tif'])])
    entry.set(direc)

def clickSelectImage(entry):
    direc = filedialog.askopenfilename(filetypes = [('Image Files', ['.png', '.jpg'])])
    entry.set(direc)

def clickSelectCSV(entry):
    direc = filedialog.askopenfilename(filetypes = [('Image Files', ['.csv'])])
    entry.set(direc)

lbl3 = Label(tab_markers, text="Create Marker", justify=CENTER,font=("Arial Bold", 24))
lbl3.grid(column=1, row=0)

#Upload the marker image to firebasestorage
def uploadToCloudStorage (path) :
    os.environ["GOOGLE_APPLICATION_CREDENTIALS"]="YOUR_APPLICATION_CREDENTIALS"
    client = storage.Client()
    bucket = client.get_bucket('YOUR_FIREBASE_BUCKET')
    # posting to firebase storage
    imageBlob = bucket.blob("/")
    separatePath = path.split('/')
    name = separatePath[-1]
    imagePath = path
    imageBlob = bucket.blob(name)
    imageBlob.upload_from_filename(imagePath)

    return 'https://firebasestorage.googleapis.com/v0/b/'+'YOUR_APPLICATIONSTORAGE_URL'+'/o/'+name+'?alt=media'

#Get a channel form and its limit from a CSV
def setArrayGraphFromCSV(path,marker):
    maioresElev = [0,0]
    menorElev = 9999
    i = 0
    array = []
    with open(path, mode='r') as infile:
        reader = csv.reader(infile)
        next(reader)
        for row in reader:
            array.append(row)
            if(float(row[1]) > maioresElev[i%2]):
                i+=1
                maioresElev[i%2] = float(row[1])
            
            if(float(row[1]) < menorElev):
                menorElev = float(row[1])
            
    if (maioresElev[0] > maioresElev[1]):
        marker["limit"] = maioresElev[0]
    else:
        marker["limit"] = maioresElev[1]
    marker["graphArray"] = array

#Send a marker info to firebase
def sendMarker (markerStrings):
    marker = {
        "coord" : {
            "lat": markerStrings["lat"].get(),
            "long": markerStrings["long"].get()
        },
        "description": markerStrings["description"].get(),
        "image": "",
        "limit": 0,
        "interval": 60,
        "graphArray": [],
        "depths": []
    }
    
    if marker["coord"]["lat"] != '' and marker["coord"]["long"] != ''\
    and marker["description"]!= '' and os.path.exists(os.path.dirname(markerStrings["csvDir"].get()))\
    and os.path.exists(os.path.dirname(markerStrings["imgDir"].get())):

        marker['image'] = uploadToCloudStorage(markerStrings["imgDir"].get())
        print(marker['image'])
        setArrayGraphFromCSV(markerStrings["csvDir"].get(),marker)

        db = firebase.database()
        db.child("markers").push(marker)

        messagebox.showinfo('Success', 'Data sent to server!')
    else:
        messagebox.showinfo('Error', 'Please Fill All Variables')


for i in range(1) :
    marker = {
        "lat": StringVar(),
        "long": StringVar(),
        "csvDir": StringVar(),
        "description": StringVar(),
        "imgDir": StringVar()
    }
    lbl4 = Label(tab_markers, text="Lat:", justify=LEFT,font=("Arial Bold", 24))
    lbl4.grid(column=0, row=(i*2)+1)

    markerLatBlock = Entry(tab_markers,width=40, font=("Arial", 18), textvariable=marker["lat"])
    markerLatBlock.grid(column=1, row=(i*2)+1)

    lbl5 = Label(tab_markers, text="Lng:", justify=LEFT,font=("Arial Bold", 24))
    lbl5.grid(column=0, row=(i*2)+2)

    markerLngBlock = Entry(tab_markers,width=40, font=("Arial", 18), textvariable=marker["long"])
    markerLngBlock.grid(column=1, row=(i*2)+2)

    lbl6 = Label(tab_markers, text="CSV:", justify=LEFT,font=("Arial Bold", 24))
    lbl6.grid(column=0, row=(i*2)+3)

    markercsvBlock = Entry(tab_markers,width=40, font=("Arial", 18), textvariable=marker["csvDir"])
    markercsvBlock.grid(column=1, row=(i*2)+3)
    btncsvSelect = Button(tab_markers, text="Choose File", bg="grey", fg="black", command=partial(clickSelectCSV,marker["csvDir"]))
    btncsvSelect.grid(column=2, row=(i*2)+3)

    lbl7 = Label(tab_markers, text="Description:", justify=LEFT,font=("Arial Bold", 24))
    lbl7.grid(column=0, row=(i*2)+4)

    markerDescBlock = Entry(tab_markers,width=40, font=("Arial", 18), textvariable=marker["description"])
    markerDescBlock.grid(column=1, row=(i*2)+4)

    lbl8 = Label(tab_markers, text="Image:", justify=LEFT,font=("Arial Bold", 24))
    lbl8.grid(column=0, row=(i*2)+5)

    markerImgBlock = Entry(tab_markers,width=40, font=("Arial", 18), textvariable=marker["imgDir"])
    markerImgBlock.grid(column=1, row=(i*2)+5)
    btnImgSelect = Button(tab_markers, text="Choose File", bg="grey", fg="black", command=partial(clickSelectImage,marker["imgDir"]))
    btnImgSelect.grid(column=2, row=(i*2)+5)

    btnImgSelect = Button(tab_markers, text="Create", bg="grey", fg="black", command=partial(sendMarker,marker))
    btnImgSelect.grid(column=2, row=(i*2)+6)

def buildForecastTab():
    lbl = Label(tab_forecast,text="Select Destination Folder:", justify=LEFT,font=("Arial Bold", 24))
 
    lbl.grid(column=0, row=0)

    folderEntry = StringVar()
    folderDir = Entry(tab_forecast,width=40, font=("Arial", 18), textvariable=folderEntry)
    folderDir.grid(column=0, row=1)
    btnSelect = Button(tab_forecast,text="Choose Folder", bg="honeydew3", fg="black", command=partial(clickSelectFolder,folderEntry))
    
    btnSelect.grid(column=1, row=1)

    btn = Button(tab_forecast,text="Create", bg="DarkOliveGreen2", fg="black", command=partial(createForecastCSV, folderEntry))
    btn.grid(column=1, row=2)

buildForecastTab()

btnSelect = Button(tab_areas, text="Choose File", bg="grey", fg="black", command=partial(clickSelectFile,fileEntry))
 
btnSelect.grid(column=1, row=1)

btn = Button(tab_areas, text="Send to app", bg="grey", fg="black", command=partial(sendClicked,fileEntry))
 
btn.grid(column=1, row=7)

tab_control.pack(expand=1, fill='both')
window.mainloop()