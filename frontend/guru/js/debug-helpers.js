// Tambahkan fungsi ini untuk debugging
function debugJSONResponse(responseText) {
    try {
        // Coba parse untuk melihat error detail
        JSON.parse(responseText);
    } catch (e) {
        console.error("JSON Parse Error Details:");
        console.error("Error position:", e.pos);
        console.error("Error at character:", responseText[e.pos]);
        console.error("Context:", responseText.substring(e.pos - 10, e.pos + 10));
        
        // Cari karakter yang tidak valid
        for (let i = 0; i < Math.min(responseText.length, 1000); i++) {
            if (responseText.charCodeAt(i) > 127) {
                console.warn(`Non-ASCII character at position ${i}:`, responseText[i], responseText.charCodeAt(i));
            }
        }
    }
}