/* CWE-562: Return of Stack Variable Address (BAD)
 * Expected detection: dangling
 */
int *leak(void) {
    int local = 42;
    return &local;  /* <-- address of local outlives the stack frame */
}

int main(void) {
    int *p = leak();
    return *p;
}
