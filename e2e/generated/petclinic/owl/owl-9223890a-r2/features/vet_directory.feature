Feature: Veterinarian directory
  Veterinarians can be listed and read by id.

  Scenario: Listing veterinarians succeeds
    When the veterinarian list is requested
    Then the vet API response status is 200
    And the veterinarian list body is not empty

  Scenario: A listed veterinarian can be fetched by id
    When the veterinarian list is requested
    And the first listed veterinarian is fetched by id when any are present
    Then the veterinarian detail request succeeded if a veterinarian was listed

  Scenario: Fetching an unknown veterinarian is rejected
    When an unknown veterinarian id is fetched
    Then the vet API response is a client error
