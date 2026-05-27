// Phase 3 target: detector "div_zero" should flag line 4.
int main(void) {
    int a = 10;
    int b = a / 0;  // <-- division by literal zero
    return b;
}
