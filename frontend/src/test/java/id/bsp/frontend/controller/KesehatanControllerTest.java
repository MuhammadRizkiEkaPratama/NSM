package id.bsp.frontend.controller;

import org.junit.jupiter.api.Test;
import org.springframework.web.client.ResourceAccessException;

import java.net.ConnectException;
import java.net.SocketTimeoutException;
import java.net.UnknownHostException;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

/** Tests that error messages on the Health page become sentences and the word "null" stops leaking (e.g. `I/O error on GET request ...: null` when uvicorn is down). Uses the same wrapper shape Spring throws (ResourceAccessException wrapping a message-less ConnectException). No Spring context, so it runs with MySQL down. */
class KesehatanControllerTest {

    private final KesehatanController c = new KesehatanController(null, null, null);

    @Test
    void uvicornMatiJadiKalimat() {
        // The exact exception RestTemplate throws when nothing listens on port 8000: empty cause message.
        Exception e = new ResourceAccessException(
                "I/O error on GET request for \"http://localhost:8000/kesehatan\": null",
                new ConnectException());

        String hasil = c.ringkasGalat(e);

        assertEquals("sambungan ditolak, tidak ada yang mendengarkan di alamat itu",
                hasil);
        assertFalse(hasil.contains("null"), "kata null tidak boleh sampai ke layar");
        assertFalse(hasil.contains("I/O error"),
                "istilah teknis Spring tidak boleh sampai ke layar");
    }

    @Test
    void tidakMenyebutProsesTertentu() {
        // The method is also used by the MySQL and email checkers, so a message naming "uvicorn" or "port 8000" would appear in the wrong place.
        String hasil = c.ringkasGalat(new ResourceAccessException("x", new ConnectException()));
        assertFalse(hasil.toLowerCase().contains("uvicorn"));
        assertFalse(hasil.contains("8000"));
    }

    @Test
    void timeoutDibedakanDariSambunganDitolak() {
        String hasil = c.ringkasGalat(
                new ResourceAccessException("x", new SocketTimeoutException()));
        assertTrue(hasil.contains("batas waktu"), "dapat: " + hasil);
        assertFalse(hasil.contains("ditolak"),
                "timeout dan sambungan ditolak dua gejala berbeda dengan "
                        + "langkah perbaikan yang berbeda");
    }

    @Test
    void hostTidakDikenal() {
        String hasil = c.ringkasGalat(
                new ResourceAccessException("x", new UnknownHostException("smtp.salah")));
        assertTrue(hasil.contains("host"), "dapat: " + hasil);
    }

    @Test
    void galatBiasaTetapApaAdanya() {
        // An error that is not a network failure must not be replaced by a guess.
        String hasil = c.ringkasGalat(new IllegalStateException("tabel users hilang"));
        assertEquals("tabel users hilang", hasil);
    }

    @Test
    void ekorNullDipotong() {
        // Spring appends ": null" when the cause has no message; it must be trimmed.
        String hasil = c.ringkasGalat(new IllegalStateException("gagal membaca berkas: null"));
        assertEquals("gagal membaca berkas", hasil);
    }

    @Test
    void galatTanpaPesanTidakJadiKosong() {
        String hasil = c.ringkasGalat(new IllegalStateException());
        assertTrue(hasil.contains("IllegalStateException"), "dapat: " + hasil);
        assertFalse(hasil.isBlank());
    }

    @Test
    void rantaiPenyebabMelingkarTidakMenggantung() {
        // Guard: a getCause() chain pointing at itself must not loop forever.
        Exception e = new IllegalStateException("berputar") {
            @Override public synchronized Throwable getCause() { return this; }
        };
        assertEquals("berputar", c.ringkasGalat(e));
    }
}
