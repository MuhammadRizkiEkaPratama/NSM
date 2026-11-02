package id.bsp.frontend.ws;

import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNull;

/** Guards the "do not rebroadcast identical content" check. It once never fired: it compared raw JSON, but Python's answer includes a `diperiksa` timestamp, so identical answers always differed and every browser redrew the map every two seconds. */
class TopologiBroadcasterTest {

    @Test
    void sidikDiambilDariJsonMentah() {
        String json = "{\"perangkat\":[],\"diperiksa\":\"2026-08-14T09:00:00\","
                    + "\"sidik\":\"aba8eddee114e8e4c0ffee00d15ea5e0deadbeef\"}";
        assertEquals("aba8eddee114e8e4c0ffee00d15ea5e0deadbeef",
                TopologiBroadcaster.sidikDari(json));
    }

    @Test
    void sidikYangSamaDikenaliWALAUPUNJamnyaBerbeda() {
        // The case that used to slip through: same content, different time. As text they differ; the fingerprint (`sidik`) is equal.
        String a = "{\"diperiksa\":\"2026-08-14T09:00:00\",\"sidik\":\"abc123def456\"}";
        String b = "{\"diperiksa\":\"2026-08-14T09:00:02\",\"sidik\":\"abc123def456\"}";

        org.junit.jupiter.api.Assertions.assertNotEquals(a, b,
                "prasyarat uji: teksnya memang berbeda");
        assertEquals(TopologiBroadcaster.sidikDari(a), TopologiBroadcaster.sidikDari(b),
                "isi yang sama harus menghasilkan sidik yang sama");
    }

    @Test
    void tanpaSidikDijawabNull() {
        // Older Python responses lack `sidik`; the broadcaster must detect that and fall back to full text comparison.
        assertNull(TopologiBroadcaster.sidikDari("{\"perangkat\":[]}"));
    }

    @Test
    void polanyaTidakTertipuFieldLainYangMiripNamanya() {
        // `"sidik_lama"` is not `"sidik"`: without the closing quote on the field name, a sloppy pattern would pick the wrong value.
        String json = "{\"sidik_lama\":\"1111111111\",\"sidik\":\"2222222222\"}";
        assertEquals("2222222222", TopologiBroadcaster.sidikDari(json));
    }
}
