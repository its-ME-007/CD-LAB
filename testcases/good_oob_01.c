/* CWE-787 / CWE-125 (GOOD baseline)
 * Expected detection: none
 */
int main(void) {
    int arr[3] = {1, 2, 3};
    return arr[2];  /* in-bounds */
}
