package glue;

import glue.support.ApiSupport;
import io.cucumber.java.en.Given;
import io.cucumber.java.en.Then;
import io.cucumber.java.en.When;
import io.restassured.response.Response;
import io.restassured.specification.RequestSpecification;
import td.harness.Harness;

import java.util.HashMap;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;

public class ReservationValidationSteps {

    private Map<String, Object> submitted;
    private String reservationId;
    private Response response;

    @When("a reservation is submitted with the invalid variant {string}")
    public void submitInvalidVariant(String variant) {
        RequestSpecification spec = Harness.authed().contentType("application/json");
        Map<String, Object> body;
        switch (variant) {
            case "empty object":
                response = spec.body("{}").post("/api/reservations");
                break;
            case "no body":
                response = spec.post("/api/reservations");
                break;
            case "negative nights":
                body = ApiSupport.newReservationBody(-1);
                response = spec.body(body).post("/api/reservations");
                break;
            case "blank pet name":
                body = ApiSupport.newReservationBody(2);
                body.put("petName", "");
                response = spec.body(body).post("/api/reservations");
                break;
            default:
                throw new IllegalArgumentException("Unknown variant: " + variant);
        }
    }

    @Then("the reservation validation response status is {int}")
    public void validationStatusIs(int expected) {
        assertThat(response.statusCode()).as("response body: %s", response.asString()).isEqualTo(expected);
    }

    @Given("a valid reservation exists for the validation test")
    public void validReservationExists() {
        submitted = ApiSupport.newReservationBody(2);
        Response created = Harness.authed().contentType("application/json").body(submitted).post("/api/reservations");
        assertThat(created.statusCode()).as("create reservation: %s", created.asString()).isBetween(200, 299);
        reservationId = ApiSupport.extractId(created);
        assertThat(reservationId).isNotBlank();
    }

    @When("the validation reservation is updated with {int} nights")
    public void updateWithNights(int nights) {
        Map<String, Object> body = new HashMap<>(submitted);
        body.put("nights", nights);
        response = Harness.authed().contentType("application/json").body(body).put("/api/reservations/" + reservationId);
    }
}
