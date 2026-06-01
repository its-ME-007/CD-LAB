/* CWE-562: Return of Stack Variable Address (GOOD baseline)
 * Expected detection: none
 */
static int g = 42;

int *safe(void) {
    return &g;      /* address of a static — survives across calls */
}

int main(void) {
    int *p = safe();
    return *p;
}
