import sys, json, collections, random
sys.path.append("src")
from pathlib import Path
from datetime import datetime, timedelta
from dataclasses import dataclass
from operator import itemgetter as at
from operator import attrgetter as dot
import pandas as pd
import numpy as np
from flask import Flask, request, send_from_directory, render_template, redirect, url_for, jsonify, Response, flash
from werkzeug.utils import secure_filename
from typing import List, Dict, Tuple, Optional
from vecsim import SciKitIndex, RedisIndex
from PIL import Image
import torch
import clip

__dir__ = Path(__file__).absolute().parent
upload_dir = __dir__ / "upload"
data_dir = __dir__ / "data"
upload_dir.mkdir(exist_ok=True)
NUMBER_OF_RESULTS = 12
app = Flask(__name__)
cart = set()

@dataclass
class Recommendation:
    id: int
    image: str
    title: str
    highlight: bool
    distance: float

@dataclass
class Item:
    id : int
    image: str
    title : str



@app.route('/favicon.ico')
def favicon():
    return send_from_directory('assets', 'favicon.ico')

@app.route('/assets/<path:path>')
def serve_assets(path):
    return send_from_directory('assets', path)


def allowed_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in {'jpg', 'jpeg', 'png'}

def embed_image(image_path):
    with torch.no_grad():
        device = "cuda" if torch.cuda.is_available() else "cpu"
        model, preprocess = clip.load("ViT-B/32", device=device)
        image = preprocess(Image.open(image_path)).unsqueeze(0).to(device)
        return model.encode_image(image).cpu()

def embed_text(text):
    with torch.no_grad():
        device = "cuda" if torch.cuda.is_available() else "cpu"
        model, preprocess = clip.load("ViT-B/32", device=device)
        text_tokens = clip.tokenize(text, truncate=True).to(device)
        return model.encode_text(text_tokens).cpu()

@app.route('/imgsearch', methods=['POST','GET'])
def imgsearch():
    if 'file' not in request.files:
        flash('No file part')
        return redirect(request.url)
    file = request.files['file']
    if file.filename == '':
        flash('No selected file')
        return redirect(request.url)
    if file and allowed_file(file.filename):
        filename = secure_filename(file.filename)
        file.save(upload_dir/filename)

        vec = embed_image(upload_dir/filename)
        (upload_dir/filename).unlink()
        cartvec = sim.get_items(cart)
        lst = [t for t in cartvec]
        avg = []
        if lst:
            avg = [np.average(lst, axis=0)]
            avg.append(vec.numpy())
            w_avg = np.average(avg, axis=0, weights=[0.1, 0.9])
            dists, ids = sim.search(w_avg ,NUMBER_OF_RESULTS)
        else:
            dists, ids = sim.search(vec ,NUMBER_OF_RESULTS)
    
        df_results = df[df["id"].isin(ids)]

        recs=[
            Recommendation(row["id"],row["primary_image"],row["title"], row["id"] in cart,round(d*100,3))
            for d,(idx,row) in sorted(zip(dists,df_results.iterrows()))
        ]
        return render_template('index.html', items=recs, recommendations=recs)
    else:
        return redirect(url_for('index'))

@app.route('/')
def index():
    recs=[
    ]
    return render_template('index.html', recommendations=recs)

@app.route('/txtsearch', methods=['POST'])
def txtsearch():
    txt = str(request.form.get('txt', ""))
    vec = embed_text(txt)
    cartvec = sim.get_items(cart)
    lst = [t for t in cartvec]
    avg = []
    if lst:
        avg = [np.average(lst, axis=0)]
        avg.append(vec.numpy())
        w_avg = np.average(avg, axis=0, weights=[0.1, 0.9])
        dists, ids = sim.search(w_avg ,NUMBER_OF_RESULTS)
    else:
        dists, ids = sim.search(vec ,NUMBER_OF_RESULTS)
    
    df_results = df[df["id"].isin(ids)]

    recs=[
        Recommendation(row["id"],row["primary_image"],row["title"], row["id"] in cart,round(d*100,3))
        for d,(idx,row) in sorted(zip(dists,df_results.iterrows()))
    ]
    return render_template('results.html', recommendations=recs)


@app.after_request
def add_no_cache(response):
    if request.endpoint != "static":
        response.headers["Cache-Control"] = "no-cache"
        response.headers["Pragma"] = "no-cache"
    return response


@app.errorhandler(404)
def page_not_found(e):
    return render_template("404.html")

@app.route('/cart/<id>', methods=['GET'])
def add_to_cart(id):
    df_results = df[df["id"].isin([id])]
    recs=[
        Recommendation(row["id"],row["primary_image"],row["title"], row["id"] in cart,1)
        for (idx,row) in sorted(df_results.iterrows())
    ]
    if id in cart:
        cart.remove(id)
        return render_template('toggle.html', rec=recs[0])
    else:
        cart.add(id)
        return render_template('toggle.html', rec=recs[0])


if __name__ == "__main__":
    print("Loading data...")
    SAMPLE_SIZE = 2000
    with (data_dir/"clip_ids.json").open('r') as f:
            embedding_ids = json.load(f)
    df = pd.read_parquet(data_dir/"product_images.parquet")  
    df=df[df["primary_image"].str.endswith(".jpg")|df["primary_image"].str.endswith(".png")].rename(columns={"asin":"id"})
    df["title"]=df["title"].fillna("")
    df["has_emb"]=df["id"].isin(embedding_ids)
    df=df[df["has_emb"]]

    print("Indexing...")
    sim = SciKitIndex("cosine",512)
    item_embedding = np.load(data_dir/"clip_emb.npy")
    sim.add_items(item_embedding, embedding_ids)
    sim.init()
    print("Starting server...")
    app.run(port=8080, host='0.0.0.0', debug=True)
