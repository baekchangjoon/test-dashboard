Feature: Veterinarian directory

  Scenario: List all veterinarians
    When the vet client lists all veterinarians
    Then the vet response status is 200
    And the vet response body is not empty

  Scenario: Every listed veterinarian can be read individually
    Given the vet client has fetched the veterinarian list
    When the vet client reads each listed veterinarian by id
    Then every individual veterinarian response has status 200

  Scenario: Reading an unknown veterinarian is rejected
    When the vet client reads veterinarian id 987654321
    Then the vet response is a client error
