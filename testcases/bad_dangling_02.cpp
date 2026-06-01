/* CWE-562: Return of Address of Stack Variable (BAD)
 * C++ idiom: returning the address of a local from a function.
 * Expected detection: dangling
 */
int* makePtr() {
    int local = 10;
    return &local;      /* <-- address of stack variable escapes */
}

int main() {
    int* p = makePtr();
    return *p;
}
