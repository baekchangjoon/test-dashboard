package glue;

import static org.assertj.core.api.Assertions.assertThat;

import io.cucumber.java.en.Then;
import io.cucumber.java.en.When;
import io.restassured.response.Response;
import java.util.List;
import td.harness.Harness;

public class VetDirectorySteps {

    private Response listResponse;
    private Response response;
    private String firstVetId;

    @When("the veterinarian list is requested")
    public void requestList() {
        listResponse = Harness.authed().get("/api/vets");
        response = listResponse;
    }

    @Then("the vet API response status is {int}")
    public void statusIs(int expected) {
        assertThat(response.statusCode()).as(response.asString()).isEqualTo(expected);
    }

    @Then("the veterinarian list body is not empty")
    public void listNotEmpty() {
        assertThat(response.asString()).isNotBlank();
    }

    @When("the first listed veterinarian is fetched by id when any are present")
    public void fetchFirst() {
        firstVetId = firstId(listResponse);
        if (firstVetId != null) {
            response = Harness.authed().get("/api/vets/" + firstVetId);
        }
    }

    @Then("the veterinarian detail request succeeded if a veterinarian was listed")
    public void detailSucceeded() {
        assertThat(listResponse.statusCode()).as(listResponse.asString()).isEqualTo(200);
        if (firstVetId != null) {
            assertThat(response.statusCode()).as(response.asString()).isEqualTo(200);
            assertThat(response.asString()).isNotBlank();
        }
    }

    @When("an unknown veterinarian id is fetched")
    public void fetchUnknown() {
        response = Harness.authed().get("/api/vets/987654321");
    }

    @Then("the vet API response is a client error")
    public void clientError() {
        assertThat(response.statusCode()).as(response.asString()).isBetween(400, 499);
    }

    private String firstId(Response r) {
        String[] paths = {"id", "vetList.id"};
        for (String path : paths) {
            try {
                List<Object> ids = r.jsonPath().getList(path);
                if (ids != null) {
                    for (Object id : ids) {
                        if (id != null) {
                            return String.valueOf(id);
                        }
                    }
                }
            } catch (RuntimeException e) {
                continue;
            }
        }
        return null;
    }
}
