"""Build the synthetic fixture pages used by the offline tests.

These are hand-written stand-ins, not captures: they exist to prove that the
JSON strategy and the HTML strategy each find listings on their own.  Replace
them with real captures (``python -m gravelscout probe`` writes them to
``debug/``) whenever a site's markup needs to be pinned down.
"""
import json
import pathlib

HERE = pathlib.Path(__file__).parent

NEXT_ADS = {
    "props": {"pageProps": {"adList": {"ads": [
        {"adId": 191861429, "name": "Gravel bicikl Giant Revolt 2 vel. S/52",
         "price": "1.450 €", "currency": "EUR",
         "adUrl": "/bicikli/drumski-trkacki/gravel-bicikl/oglas/191861429",
         "location": {"name": "Beograd"},
         "images": [{"url": "https://img.kupujemprodajem.com/1.jpg"}],
         "description": "Shimano GRX 600 2x11, hidraulicne disk kocnice, 700x40c"},
        {"adId": 191861430, "name": "Brdski bicikl Scott Aspect 27.5",
         "price": "350 €", "currency": "EUR",
         "adUrl": "/bicikli/mtb/oglas/191861430",
         "location": {"name": "Novi Sad"},
         "description": "Shimano Altus, mehanicke disk kocnice"},
    ]}}}
}

KP_HTML = """<!doctype html><html><head><title>Bicikli</title>
<script id="__NEXT_DATA__" type="application/json">%s</script></head>
<body><main>ads render client side</main></body></html>""" % json.dumps(NEXT_ADS, ensure_ascii=False)

TWOBIKE_HTML = """<!doctype html><html><head><title>Cikloberza</title></head><body>
<nav><a href="/cikloberza/mali-oglasi/bicikli-6">Bicikli</a>
     <a href="/cikloberza/mali-oglasi/bicikli-6/gravel-ciklokros-189">Gravel/Ciklokros</a></nav>
<div class="ads">
  <div class="ad">
    <a href="/cikloberza/mali-oglasi/bicikli-6/gravel-ciklokros-189/canyon-grizl-7-44231">
      Canyon Grizl 7 GRX RX810, hidraulicne disk kocnice, vel. XS</a>
    <img src="/media/ads/44231_1.jpg" alt="Canyon Grizl 7">
    <span class="price">1.850 &euro;</span>
    <span class="city">Beograd</span>
  </div>
  <div class="ad">
    <a href="/cikloberza/mali-oglasi/bicikli-6/drumski-trkacki-8/bianchi-via-nirone-9911">
      Bianchi Via Nirone 7 Sora, vel. 53</a>
    <img src="/media/ads/9911_1.jpg" alt="Bianchi">
    <span class="price">120.000 din</span>
  </div>
  <a href="/cikloberza/mali-oglasi/bicikli-6/gravel-ciklokros-189?page=2">Sledeca strana</a>
</div></body></html>"""

if __name__ == "__main__":
    (HERE / "kupujemprodajem_list.html").write_text(KP_HTML, encoding="utf-8")
    (HERE / "2bike_list.html").write_text(TWOBIKE_HTML, encoding="utf-8")
    print("fixtures written")
