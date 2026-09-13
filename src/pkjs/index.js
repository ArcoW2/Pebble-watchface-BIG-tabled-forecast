/*
 * Phone side. One geolocation fix feeds two requests:
 *   - reverse geocode  -> PLACE  "Houten, NL"
 *   - Open-Meteo       -> WX     "code,temp,wind,dir|code,max,min,wind,dir|..."
 *
 * Unchanged from the Alloy version apart from dropping the Moddable proxy:
 * a C app talks to PebbleKit JS the same way.
 *
 * PKJS is ES5-era: no arrow functions, no const/let, no fetch.
 */

var REFRESH_MS = 15 * 60 * 1000;
var FORECAST_DAYS = 5;
var WIND_UNIT = "kmh";          // kmh | ms | mph | kn

var lastPlace = "";
var lastWx = "";

var PREFIXES = [
    "Gemeente ", "Municipality of ", "Gemeinde ",
    "Commune de ", "Comune di ", "Ciudad de ",
    "City of ", "Borough of "
];

function tidy(name) {
    if (!name) return "";
    for (var i = 0; i < PREFIXES.length; i++) {
        if (name.indexOf(PREFIXES[i]) === 0)
            return name.slice(PREFIXES[i].length);
    }
    return name;
}

/* The outbox carries one message at a time. Two parallel requests finishing
   close together would otherwise have the second rejected, so queue them. */
var outbox = [];
var sending = false;

function pump() {
    if (sending || outbox.length === 0) return;
    sending = true;

    var item = outbox.shift();
    var payload = {};
    payload[item.key] = item.text;

    Pebble.sendAppMessage(payload,
        function () {
            console.log(item.key + " sent: " + item.text);
            sending = false;
            pump();
        },
        function () {
            console.log(item.key + " nack, retrying once");
            sending = false;
            if (!item.retried) {
                item.retried = true;
                outbox.push(item);
            }
            setTimeout(pump, 1000);
        });
}

function send(key, text) {
    outbox.push({ key: key, text: text, retried: false });
    pump();
}

function geocode(lat, lon) {
    var xhr = new XMLHttpRequest();
    xhr.open("GET", "https://api.bigdatacloud.net/data/reverse-geocode-client" +
        "?latitude=" + lat.toFixed(3) + "&longitude=" + lon.toFixed(3) +
        "&localityLanguage=en", true);

    xhr.onload = function () {
        try {
            var d = JSON.parse(xhr.responseText);
            /* locality is usually the settlement; city often carries the
               municipality, which is why "Gemeente Houten" showed up */
            var name = tidy(d.locality) || tidy(d.city) || tidy(d.principalSubdivision);
            var cc = d.countryCode || "";
            if (!name && !cc) return;
            var text = cc ? (name + ", " + cc) : name;
            if (text === lastPlace) return;
            lastPlace = text;
            send("PLACE", text);
        } catch (err) {
            console.log("geocode parse failed: " + err);
        }
    };
    xhr.onerror = function () { console.log("geocode request failed"); };
    xhr.send();
}

function weather(lat, lon) {
    var xhr = new XMLHttpRequest();
    xhr.open("GET", "https://api.open-meteo.com/v1/forecast" +
        "?latitude=" + lat.toFixed(3) + "&longitude=" + lon.toFixed(3) +
        "&current=temperature_2m,weather_code,wind_speed_10m,wind_direction_10m" +
        "&daily=weather_code,temperature_2m_max,temperature_2m_min," +
        "wind_speed_10m_max,wind_direction_10m_dominant" +
        "&wind_speed_unit=" + WIND_UNIT +
        "&timezone=auto&forecast_days=" + FORECAST_DAYS, true);

    xhr.onload = function () {
        try {
            var d = JSON.parse(xhr.responseText);
            var c = d.current, y = d.daily;
            var parts = [];

            parts.push([
                c.weather_code,
                Math.round(c.temperature_2m),
                Math.round(c.wind_speed_10m),
                Math.round(c.wind_direction_10m)
            ].join(","));

            for (var i = 0; i < y.time.length && i < FORECAST_DAYS; i++) {
                parts.push([
                    y.weather_code[i],
                    Math.round(y.temperature_2m_max[i]),
                    Math.round(y.temperature_2m_min[i]),
                    Math.round(y.wind_speed_10m_max[i]),
                    Math.round(y.wind_direction_10m_dominant[i])
                ].join(","));
            }

            var text = parts.join("|");
            if (text === lastWx) return;
            lastWx = text;
            send("WX", text);
        } catch (err) {
            console.log("weather parse failed: " + err);
        }
    };
    xhr.onerror = function () { console.log("weather request failed"); };
    xhr.send();
}

function update() {
    navigator.geolocation.getCurrentPosition(
        function (pos) {
            geocode(pos.coords.latitude, pos.coords.longitude);
            weather(pos.coords.latitude, pos.coords.longitude);
        },
        function (err) { console.log("geolocation failed: " + err.message); },
        { timeout: 15000, maximumAge: 600000 }
    );
}

Pebble.addEventListener("ready", function () {
    update();
    setInterval(update, REFRESH_MS);
});