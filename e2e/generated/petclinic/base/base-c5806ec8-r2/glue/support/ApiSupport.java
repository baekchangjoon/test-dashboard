package glue.support;

import io.restassured.response.Response;
import td.harness.Harness;

import java.time.LocalDate;
import java.util.HashMap;
import java.util.Map;
import java.util.concurrent.ThreadLocalRandom;

public final class ApiSupport {

    private ApiSupport() {
    }

    public static String suffix() {
        return Long.toString(System.nanoTime(), 36) + ThreadLocalRandom.current().nextInt(1000, 10000);
    }

    public static int randomInt(int min, int maxInclusive) {
        return ThreadLocalRandom.current().nextInt(min, maxInclusive + 1);
    }

    public static String futureDate() {
        return LocalDate.now().plusDays(randomInt(30, 3600)).toString();
    }

    public static int randomRoom() {
        return randomInt(1, 20);
    }

    public static Map<String, Object> reservationBody(String petName, String ownerEmail, int nights) {
        Map<String, Object> body = new HashMap<>();
        body.put("petName", petName);
        body.put("ownerEmail", ownerEmail);
        body.put("roomNumber", randomRoom());
        body.put("nights", nights);
        body.put("animalCount", 1);
        body.put("checkInDate", futureDate());
        return body;
    }

    public static Map<String, Object> uniqueReservationBody(int nights) {
        String s = suffix();
        return reservationBody("Pet" + s, "owner" + s + "@example.com", nights);
    }

    public static Response createReservation(Map<String, Object> body) {
        Response last = null;
        for (int attempt = 0; attempt < 6; attempt++) {
            last = Harness.authed().contentType("application/json").body(body).post("/api/reservations");
            if (last.statusCode() != 409) {
                return last;
            }
            body.put("roomNumber", randomRoom());
            body.put("checkInDate", futureDate());
        }
        return last;
    }

    public static Map<String, Object> ownerBody() {
        String s = suffix();
        Map<String, Object> body = new HashMap<>();
        body.put("address", "Street " + s);
        body.put("city", "City" + s);
        body.put("telephone", Long.toString(ThreadLocalRandom.current().nextLong(1000000000L, 10000000000L)));
        return body;
    }

    public static String extractId(Response response) {
        try {
            Object id = response.jsonPath().get("id");
            if (id != null) {
                return String.valueOf(id);
            }
        } catch (RuntimeException e) {
            // fall back to the Location header
        }
        String location = response.header("Location");
        if (location != null && !location.isBlank()) {
            String trimmed = location.endsWith("/") ? location.substring(0, location.length() - 1) : location;
            return trimmed.substring(trimmed.lastIndexOf('/') + 1);
        }
        return null;
    }

    public static String unknownId() {
        return Long.toString(900000000L + randomInt(0, 99999999));
    }
}
