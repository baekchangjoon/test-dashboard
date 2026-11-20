package glue.support;

import io.restassured.response.Response;
import java.time.LocalDate;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.concurrent.ThreadLocalRandom;

public final class ApiSupport {

    private ApiSupport() {
    }

    public static String letters(int length) {
        StringBuilder sb = new StringBuilder();
        for (int i = 0; i < length; i++) {
            sb.append((char) ('a' + ThreadLocalRandom.current().nextInt(26)));
        }
        return sb.toString();
    }

    public static String digits(int length) {
        StringBuilder sb = new StringBuilder();
        for (int i = 0; i < length; i++) {
            sb.append((char) ('0' + ThreadLocalRandom.current().nextInt(10)));
        }
        return sb.toString();
    }

    public static String petName() {
        return "Pet" + letters(8);
    }

    public static String email() {
        return "owner." + letters(10) + "@example.com";
    }

    public static int randomRoom() {
        return ThreadLocalRandom.current().nextInt(1, 21);
    }

    public static String randomFutureDate() {
        return LocalDate.now().plusDays(ThreadLocalRandom.current().nextInt(30, 700)).toString();
    }

    public static Map<String, Object> reservationBody(String petName, String ownerEmail, int roomNumber, String checkInDate, int nights) {
        Map<String, Object> body = new LinkedHashMap<>();
        body.put("petName", petName);
        body.put("ownerEmail", ownerEmail);
        body.put("roomNumber", roomNumber);
        body.put("checkInDate", checkInDate);
        body.put("nights", nights);
        body.put("animalCount", 1);
        return body;
    }

    public static Map<String, Object> uniqueReservationBody(int nights) {
        return reservationBody(petName(), email(), randomRoom(), randomFutureDate(), nights);
    }

    public static Map<String, Object> copy(Map<String, Object> source) {
        return new LinkedHashMap<>(source);
    }

    public static Object typedValue(String raw) {
        if (raw == null) {
            return null;
        }
        try {
            return Integer.valueOf(Integer.parseInt(raw.trim()));
        } catch (NumberFormatException e) {
            return raw;
        }
    }

    public static String extractId(Response response) {
        if (response == null) {
            return null;
        }
        Object id;
        try {
            id = response.jsonPath().get("id");
        } catch (Exception e) {
            id = null;
        }
        if (id != null) {
            return String.valueOf(id);
        }
        String location = response.header("Location");
        if (location != null && !location.isBlank()) {
            String trimmed = location.endsWith("/") ? location.substring(0, location.length() - 1) : location;
            return trimmed.substring(trimmed.lastIndexOf('/') + 1);
        }
        return null;
    }
}
